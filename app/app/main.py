import logging
import os
import random
import time

import boto3
from fastapi import FastAPI, HTTPException, Request, Response
import uvicorn

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("orders-api")

AWS_REGION   = os.environ.get("AWS_REGION", "us-east-1")
METRIC_NS    = os.environ.get("METRIC_NAMESPACE", "DemoApp")
SERVICE_NAME = os.environ.get("SERVICE_NAME", "orders-api")
ENVIRONMENT  = os.environ.get("ENVIRONMENT", "dev")

app = FastAPI(title="Orders API", version="1.0.0")

STATE = {"chaos": False, "requests": 0, "errors": 0, "payments": 0, "payment_errors": 0, "started": time.time()}

ORDERS = [
    {"id": "ord-1001", "customer": "Acme GmbH", "total": 249.90, "status": "shipped"},
    {"id": "ord-1002", "customer": "Globex SARL", "total": 89.00, "status": "processing"},
    {"id": "ord-1003", "customer": "Initech Ltd", "total": 1240.50, "status": "processing"},
    {"id": "ord-1004", "customer": "Umbrella SA", "total": 32.99, "status": "delivered"},
]


def emit_error_metric() -> None:
    """Push one error datapoint for the watch- alarm."""
    logger.info(f"DEBUG: emit_error_metric called | ns={METRIC_NS} service={SERVICE_NAME} region={AWS_REGION}")

    try:
        sts = boto3.client("sts", region_name=AWS_REGION)
        identity = sts.get_caller_identity()
        logger.info(f"DEBUG: running as ARN={identity.get('Arn')} account={identity.get('Account')}")
    except Exception as e:
        logger.error(f"DEBUG: STS get_caller_identity FAILED: {type(e).__name__}: {e}", exc_info=True)

    try:
        cw = boto3.client("cloudwatch", region_name=AWS_REGION)
        logger.info(f"DEBUG: cloudwatch client created, endpoint={cw.meta.endpoint_url}")

        response = cw.put_metric_data(
            Namespace=METRIC_NS,
            MetricData=[{
                "MetricName": "Errors",
                "Dimensions": [{"Name": "Service", "Value": SERVICE_NAME}],
                "Value": 1.0,
                "Unit": "Count",
            }],
        )

        status_code = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        request_id = response.get("ResponseMetadata", {}).get("RequestId")
        logger.info(f"DEBUG: put_metric_data HTTP {status_code} | RequestId={request_id}")

        if status_code == 200:
            logger.info("SUCCESS: CloudWatch accepted the metric")
        else:
            logger.error(f"SUSPICIOUS: put_metric_data returned non-200 without raising: {response}")

    except Exception as e:
        logger.error(f"FAILED put_metric_data: {type(e).__name__}: {e}", exc_info=True)


@app.get("/health")
def health():
    return {
        "status": "degraded" if STATE["chaos"] else "healthy",
        "service": SERVICE_NAME,
        "environment": ENVIRONMENT,
        "uptime_seconds": round(time.time() - STATE["started"]),
        "requests": STATE["requests"],
        "errors": STATE["errors"],
        "payments": STATE["payments"],
        "payment_errors": STATE["payment_errors"],
    }


@app.api_route("/process-payment", methods=["GET", "POST"])
async def process_payment(request: Request):
    if request.method != "POST":
        return {
            "status": "info",
            "message": "API is alive! Please send a POST request to process a payment."
        }

    STATE["requests"] += 1
    STATE["payments"] += 1
    data = await request.json()

    if STATE["chaos"] and random.random() < 0.8:
        STATE["errors"] += 1
        STATE["payment_errors"] += 1
        emit_error_metric()
        logger.error("simulated failure: payment gateway timeout")
        raise HTTPException(status_code=504, detail="payment gateway timeout")

    return {
        "status": "success",
        "message": "Payment processed",
        "received_data": data,
    }


@app.get("/api/orders")
def list_orders():
    STATE["requests"] += 1
    if STATE["chaos"] and random.random() < 0.8:
        STATE["errors"] += 1
        emit_error_metric()
        logger.error("simulated failure: connection pool exhausted")
        raise HTTPException(status_code=503, detail="connection pool exhausted")
    return {"orders": ORDERS, "count": len(ORDERS)}


@app.post("/chaos/on")
def chaos_on():
    STATE["chaos"] = True
    logger.warning("CHAOS ENABLED — service will now fail most requests")
    return {"chaos": True}


@app.post("/chaos/off")
def chaos_off():
    STATE["chaos"] = False
    logger.info("chaos disabled")
    return {"chaos": False}


@app.get("/")
def dashboard():
    return Response(content=DASHBOARD_HTML, media_type="text/html")


DASHBOARD_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Orders API — live dashboard</title>
<style>
  :root{
    --ink:#e8e4d8; --dim:#8d8878; --bg:#141a1e; --panel:#1b2329;
    --line:#2b363e; --ok:#7fb069; --bad:#e0693e; --amber:#d9a441;
  }
  @media (prefers-reduced-motion: reduce){ *{animation:none !important; transition:none !important} }
  *{box-sizing:border-box; margin:0}
  body{
    background:var(--bg); color:var(--ink);
    font-family:"IBM Plex Mono", ui-monospace, "Cascadia Mono", Menlo, monospace;
    min-height:100vh; display:grid; place-items:center; padding:24px;
  }
  main{width:min(720px,100%)}
  .eyebrow{color:var(--dim); font-size:12px; letter-spacing:.18em; text-transform:uppercase}
  h1{font-size:clamp(22px,4vw,30px); font-weight:600; margin:6px 0 20px}
  h1 em{font-style:normal; color:var(--amber)}
  .lamp{
    display:flex; align-items:center; gap:14px; background:var(--panel);
    border:1px solid var(--line); border-radius:10px; padding:18px 20px; margin-bottom:14px;
  }
  .dot{width:14px; height:14px; border-radius:50%; background:var(--ok);
       box-shadow:0 0 0 0 rgba(127,176,105,.5); animation:pulse 2.4s infinite}
  .dot.bad{background:var(--bad); box-shadow:0 0 0 0 rgba(224,105,62,.5)}
  @keyframes pulse{70%{box-shadow:0 0 0 12px rgba(0,0,0,0)}}
  .lamp b{font-size:16px; font-weight:600}
  .grid{display:grid; grid-template-columns:repeat(auto-fit,minmax(140px,1fr)); gap:10px; margin-bottom:14px}
  .stat{background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:14px 16px}
  .stat .k{color:var(--dim); font-size:11px; letter-spacing:.12em; text-transform:uppercase}
  .stat .v{font-size:20px; margin-top:4px; font-variant-numeric:tabular-nums}
  .row{display:flex; gap:10px; flex-wrap:wrap; margin-bottom:14px}
  button{
    font:inherit; font-size:13px; color:var(--ink); background:transparent;
    border:1px solid var(--line); border-radius:8px; padding:10px 16px; cursor:pointer;
  }
  button:hover{border-color:var(--amber)}
  button:focus-visible{outline:2px solid var(--amber); outline-offset:2px}
  button.danger{color:var(--bad); border-color:#4a3228}
  button.good{color:var(--ok); border-color:#2e4227}
  .log{
    background:var(--panel); border:1px solid var(--line); border-radius:10px;
    padding:14px 16px; font-size:12px; max-height:160px; overflow-y:auto;
  }
  .log .k{color:var(--dim); font-size:11px; letter-spacing:.12em; text-transform:uppercase; margin-bottom:8px}
  .log div.line{padding:3px 0; border-bottom:1px solid rgba(255,255,255,.04)}
  .log .ok-line{color:var(--ok)}
  .log .bad-line{color:var(--bad)}
  footer{color:var(--dim); font-size:12px; margin-top:16px; line-height:1.6}
  code{color:var(--amber)}
</style>
</head>
<body>
<main>
  <p class="eyebrow">demo workload · monitored by ai-ops-serverless</p>
  <h1>Orders API <em>/</em> live dashboard</h1>

  <div class="lamp">
    <span class="dot" id="dot"></span>
    <div><b id="statusText">checking…</b><div class="eyebrow" id="envText"></div></div>
  </div>

  <div class="grid">
    <div class="stat"><div class="k">uptime</div><div class="v" id="uptime">–</div></div>
    <div class="stat"><div class="k">requests</div><div class="v" id="reqs">–</div></div>
    <div class="stat"><div class="k">order errors</div><div class="v" id="errs">–</div></div>
    <div class="stat"><div class="k">payment errors</div><div class="v" id="payErrs">–</div></div>
  </div>

  <div class="row">
    <button onclick="hitOrders()">Send test order</button>
    <button onclick="hitPayment()">Send test payment</button>
  </div>
  <div class="row">
    <button class="danger" onclick="chaos(true)">Break this service</button>
    <button class="good" onclick="chaos(false)">Stop breaking it</button>
  </div>

  <div class="log">
    <div class="k">recent activity</div>
    <div id="logLines"></div>
  </div>

  <footer>
    "Break this service" flips an in-memory fault: <code>/api/orders</code> and
    <code>/process payment</code> start failing most of the time, and every
    failure emits a CloudWatch metric that the watch alarm reads.
  </footer>
</main>
<script>
const logLines = [];
function addLog(text, ok){
  logLines.unshift({text, ok, t: new Date().toLocaleTimeString()});
  logLines.length = Math.min(logLines.length, 12);
  document.getElementById('logLines').innerHTML = logLines.map(l =>
    `<div class="line ${l.ok ? 'ok-line' : 'bad-line'}">[${l.t}] ${l.text}</div>`
  ).join('');
}

async function refresh(){
  try{
    const r = await fetch('/health'); const d = await r.json();
    const bad = d.status !== 'healthy';
    document.getElementById('dot').className = 'dot' + (bad ? ' bad' : '');
    document.getElementById('statusText').textContent = bad ? 'DEGRADED — failing requests' : 'HEALTHY';
    document.getElementById('envText').textContent = d.service + ' · ' + d.environment;
    document.getElementById('uptime').textContent = d.uptime_seconds + 's';
    document.getElementById('reqs').textContent = d.requests;
    document.getElementById('errs').textContent = d.errors;
    document.getElementById('payErrs').textContent = d.payment_errors;
  }catch(e){
    document.getElementById('statusText').textContent = 'UNREACHABLE';
    document.getElementById('dot').className = 'dot bad';
  }
}
async function hitOrders(){
  try{
    const r = await fetch('/api/orders');
    addLog(r.ok ? 'GET /api/orders — 200 OK' : `GET /api/orders — ${r.status}`, r.ok);
  }catch(e){ addLog('GET /api/orders — network error', false); }
  refresh();
}
async function hitPayment(){
  try{
    const r = await fetch('/process-payment', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({amount: 42.00, order_id:'demo-' + Date.now()})
    });
    addLog(r.ok ? 'POST /process-payment — 200 OK' : `POST /process-payment — ${r.status}`, r.ok);
  }catch(e){ addLog('POST /process-payment — network error', false); }
  refresh();
}
async function chaos(on){
  await fetch('/chaos/' + (on ? 'on' : 'off'), {method:'POST'});
  addLog(on ? 'Chaos mode ENABLED' : 'Chaos mode disabled', !on);
  refresh();
}
refresh(); setInterval(refresh, 3000);
</script>
</body>
</html>"""


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)