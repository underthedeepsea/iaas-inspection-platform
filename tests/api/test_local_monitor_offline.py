"""HTTP-shaped offline contract: real Django routing/views, only ORM faked.

Explicit: .venv-web/bin/python -I -B tests/api/test_local_monitor_offline.py
No listener, DB, network, or production model; this is not S10 HTTP acceptance.
"""
def main():
    import ast, json, sys, types, socket, unittest
    from pathlib import Path
    from uuid import UUID
    from unittest.mock import patch
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root))
    from django.conf import settings
    settings.configure(DEFAULT_CHARSET="utf-8", USE_TZ=True, SECRET_KEY="offline-only")
    from django.test import RequestFactory
    from django.urls import path, include, resolve
    models = types.ModuleType("apps.core.models")
    class Environment:
        class DoesNotExist(Exception): pass
        EnvironmentType = types.SimpleNamespace(values=["DEV", "TEST", "PROD_SIM"])
    for name in ["MappingBundle", "MappingRevision"]:
        setattr(models, name, type(name, (), {}))
    models.Environment = Environment
    sys.modules[models.__name__] = models
    from apps.core import local_monitor_services as svc
    from apps.core import local_monitor_urls
    env_id = "01234567-89ab-cdef-0123-456789abcdef"
    environment = types.SimpleNamespace(pk=UUID(env_id), environment_type="DEV", is_active=True,
        metadata={"local_mapping": dict(svc.store.MOCK_METADATA)})
    def get(pk):
        if pk != environment.pk: raise Environment.DoesNotExist()
        return environment
    Environment.objects = types.SimpleNamespace(get=get)
    routes = types.ModuleType("offline_routes")
    routes.urlpatterns = [path("api/v1/local-monitor/", include(local_monitor_urls))]
    sys.modules[routes.__name__] = routes
    factory = RequestFactory()
    base = {"environment_id": env_id, **svc.store.MOCK_INFERENCE_SCOPE}
    query = {**base, "endpoint": "grid-monitor", "counter": "demo.host.cpu_busy", "start": 1700000000, "end": 1700000300, "step": 60}
    requests = 0
    def call(route, data, method="GET", content_type="application/json"):
        nonlocal requests
        url = "/api/v1/local-monitor/" + route
        req = factory.get(url, data) if method == "GET" else factory.post(url, json.dumps(data), content_type=content_type)
        response = resolve(url, urlconf=routes).func(req)
        requests += 1
        return response.status_code, json.loads(response.content)
    class Contract(unittest.TestCase):
        def test_routes_registered(self):
            source = (root / "apps/api/urls.py").read_text(); ast.parse(source)
            self.assertLess(source.index('path("local-monitor/"'), source.index('path("<path:resource>"'))
        def test_discovery_pages(self):
            found=[]; cursor=None
            for i in range(4):
                code, body=call("endpoint-metric", {**base, **({"cursor":cursor} if cursor else {})})
                self.assertEqual(code,200); self.assertTrue(body["synthetic"])
                self.assertEqual(len(body["metrics"]),37); self.assertEqual(body["has_more"],i<3)
                found += body["endpoints"]; cursor=body["cursor"]
            self.assertIsNone(cursor); self.assertEqual(tuple(found),svc.ENDPOINTS)
            self.assertEqual(call("endpoint-metric",{**base,"cursor":"https://bad"})[0],400)
        def test_batch_metadata_boundaries(self):
            code,body=call("batch-endpoint-counter",{**base,"endpoints":list(svc.ENDPOINTS)},"POST")
            self.assertEqual(code,200); self.assertEqual(len(body["items"]),100)
            self.assertEqual(len(body["items"][0]["metrics"]),37)
            self.assertEqual(call("batch-endpoint-counter",{**base,"endpoints":list(svc.ENDPOINTS)+["extra"]},"POST")[0],400)
        def test_single_all_counters_and_windows(self):
            for counter in svc.COUNTERS:
                code,body=call("data",{**query,"counter":counter})
                self.assertEqual(code,200,counter); self.assertEqual(body["counter"],counter)
                self.assertEqual(body["series"][0]["endpoint"],"grid-monitor"); self.assertIn("quality",body["series"][0])
            code,body=call("data",query); self.assertEqual(len(body["series"][0]["points"]),5)
            self.assertEqual(call("data",{**query,"fixture":"no-data"})[1]["status"],"empty")
            code,body=call("data",{**query,"counter":"demo.gpu.xid_events","fixture":"zero"})
            self.assertEqual(code,200); self.assertEqual(body["status"],"success")
            self.assertEqual(body["series"][0]["events"],[])
            self.assertEqual(call("data",{**query,"counter":"demo.gpu.ecc_sbe","end":1700000061,"step":1})[0],400)
            self.assertEqual(call("data",{**query,"counter":"demo.gpu.ecc_sbe","end":1700000060,"step":1})[0],200)
            for change in [{"counter":"x"},{"counter":["demo.host.cpu_busy","demo.gpu.temperature"]},{"step":0},{"end":1700004000},{"start":"1.2"},{"step":"060"},{"end":9999999999},{"step":1}]:
                self.assertEqual(call("data",{**query,**change})[0],400,change)
        def test_batch_status_and_100_101(self):
            payload={k:v for k,v in query.items() if k!="endpoint"}; payload["endpoints"]=list(svc.ENDPOINTS)
            code,body=call("batch-data",payload,"POST")
            self.assertEqual(code,200); self.assertEqual(len(body["items"]),100)
            self.assertEqual([body["items"][i]["status"] for i in [0,98,99]],["success","empty","failed"])
            self.assertEqual(body["errors"],[{"endpoint":"demo-node-099","code":"SYNTHETIC_FAILURE"}])
            for endpoints in [[],["grid-monitor"]*2,list(svc.ENDPOINTS)+["x"],["/etc/passwd"],["https://host"],["other"]]:
                self.assertEqual(call("batch-data",{**payload,"endpoints":endpoints},"POST")[0],400)
            for value in [True,1.2,"60",None]:
                self.assertEqual(call("batch-data",{**payload,"step":value},"POST")[0],400)
            self.assertEqual(call("batch-data",{**payload,"counter":["demo.host.cpu_busy"]},"POST")[0],400)
        def test_security_and_protocol(self):
            for route,method,payload in [("endpoint-metric","GET",base),("batch-endpoint-counter","POST",{**base,"endpoints":["grid-monitor"]}),("data","GET",query),("batch-data","POST",{**{k:v for k,v in query.items() if k!="endpoint"},"endpoints":["grid-monitor"]})]:
                for key,value in [("host","http://x"),("token","secret"),("labels",{"x":"inject"}),("unknown",1)]:
                    self.assertEqual(call(route,{**payload,key:value},method)[0],400)
                for key,value in [("source_ref","unknown"),("cluster_uid","other"),("monitor_cluster_id","/etc/passwd")]:
                    code,body=call(route,{**payload,key:value},method); self.assertEqual(code,403); self.assertIn("trace_id",body["error"])
            self.assertEqual(call("data",{**query,"environment_id":"11234567-89ab-cdef-0123-456789abcdef"})[0],404)
            for attr,value in [("is_active",False),("metadata",{}),("environment_type","REAL")]:
                old=getattr(environment,attr); setattr(environment,attr,value)
                try:self.assertEqual(call("data",query)[0],403)
                finally:setattr(environment,attr,old)
            self.assertEqual(call("data",query,"POST")[0],405)
            self.assertEqual(call("batch-data",{},"POST","text/plain")[0],415)
            self.assertEqual(call("data",{**query,"endpoint":["grid-monitor","grid-monitor"]})[0],400)
            req=factory.post("/", "{", content_type="application/json")
            self.assertEqual(local_monitor_urls.urlpatterns[-1].callback(req).status_code,400)
            req=factory.post("/?host=x", "{}", content_type="application/json")
            self.assertEqual(local_monitor_urls.urlpatterns[-1].callback(req).status_code,400)
            req=factory.post("/", "x"*65537, content_type="application/json")
            self.assertEqual(local_monitor_urls.urlpatterns[-1].callback(req).status_code,413)
    def forbidden(*args,**kwargs): raise AssertionError("Network forbidden in offline validation")
    with patch.object(socket,"socket",forbidden):
        result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Contract))
    print(json.dumps({"test_count":result.testsRun,"failures":len(result.failures),"errors":len(result.errors),"routed_requests":requests,"real_http_requests":0,"orm":"fake only","guard_fixture_query":"real","actual_model":None,"actual_usage":None}))
    return 0 if result.wasSuccessful() else 1

if __name__ == "__main__":
    raise SystemExit(main())
