"""Dashboard do robô — abre no navegador em http://127.0.0.1:8050

Uso:  py -3.13 dashboard.py
Só lê os arquivos que o bot grava na pasta logs/. Não envia ordens e só aceita
conexões do próprio computador (127.0.0.1).
"""
import csv
import json
import os
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from configuracao import PASTA, carregar_config

PORTA = 8050
LOGS = os.path.join(PASTA, "logs")


def ler_csv(caminho):
    if not os.path.exists(caminho):
        return []
    with open(caminho, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def ultimas_linhas(caminho, n=25):
    if not os.path.exists(caminho):
        return []
    with open(caminho, encoding="utf-8", errors="replace") as f:
        return [l.rstrip() for l in f.readlines()[-n:]]


def montar_dados():
    import glob
    cfg = carregar_config()
    status = {}
    arquivos = sorted(glob.glob(os.path.join(LOGS, "status_*.json")), key=os.path.getmtime, reverse=True)
    modo = cfg["modo"]
    if arquivos:
        modo = os.path.basename(arquivos[0])[len("status_"):-len(".json")]  # rótulo, ex.: real-BTCBRL
        with open(arquivos[0], encoding="utf-8") as f:
            status = json.load(f)
        idade = (datetime.now(timezone.utc) - datetime.fromisoformat(status["atualizado_em"])).total_seconds()
        status["segundos_desde_atualizacao"] = idade

    trades = ler_csv(os.path.join(LOGS, f"trades_{modo}.csv"))
    lucros = [float(t["lucro"]) for t in trades]
    ganhos = [l for l in lucros if l > 0]
    perdas = [l for l in lucros if l <= 0]
    resumo = {
        "trades": len(lucros),
        "lucro_total": sum(lucros),
        "acerto": len(ganhos) / len(lucros) if lucros else None,
        "fator_lucro": (sum(ganhos) / abs(sum(perdas))) if perdas and sum(perdas) != 0 else None,
    }
    return {
        "config": {"modo": status.get("modo", cfg["modo"]), "par": status.get("par", cfg["par"]),
                   "timeframe": cfg["timeframe"], "estrategia": cfg["estrategia"]["tipo"], "risco": cfg["risco"]},
        "status": status, "resumo": resumo,
        "trades": trades[-30:][::-1],
        "curva": ler_csv(os.path.join(LOGS, f"patrimonio_{modo}.csv"))[-2000:],
        "log": ultimas_linhas(os.path.join(LOGS, f"bot_{modo}.log")),
    }


PAGINA_ARQ = os.path.join(PASTA, "painel", "index.html")
CONFIG_LOCAL = b'window.PAINEL = {fonte: "local"};'



class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/api"):
            corpo, tipo = json.dumps(montar_dados(), default=str).encode(), "application/json"
        elif self.path in ("/", "/index.html"):
            with open(PAGINA_ARQ, "rb") as f:
                corpo, tipo = f.read(), "text/html; charset=utf-8"
        elif self.path.startswith("/config.js"):
            corpo, tipo = CONFIG_LOCAL, "application/javascript"
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", tipo)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(corpo)

    def log_message(self, *args):
        pass  # não polui o terminal


def main():
    servidor = ThreadingHTTPServer(("127.0.0.1", PORTA), Handler)
    url = f"http://127.0.0.1:{PORTA}"
    print(f"Dashboard rodando em {url}  (Ctrl+C para fechar)")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    servidor.serve_forever()


if __name__ == "__main__":
    main()
