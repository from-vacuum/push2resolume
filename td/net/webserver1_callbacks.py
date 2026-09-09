"""webserverDAT callbacks -- serves live state JSON for the local
push2_live_overlay.html page (not the published claude.ai artifact, which
cannot reach localhost). GET /state -> full snapshot."""
from typing import Dict, Any
import json


def _snapshot():
	return parent.PushResolume.op('logic/mod_ledpainter').module.Snapshot(parent.PushResolume)


def onHTTPRequest(dat: webserverDAT, request: Dict[str, Any],
                   response: Dict[str, Any]) -> Dict[str, Any]:
	response['Access-Control-Allow-Origin'] = '*'
	response['Cache-Control'] = 'no-store'
	if request.get('uri', '').split('?')[0] == '/lcd.png':
		import cv2
		pixels = parent.PushResolume.op('display/mod_display').module.RenderLCD(_snapshot())
		ok, encoded = cv2.imencode('.png', cv2.cvtColor(pixels, cv2.COLOR_RGBA2BGRA))
		response['statusCode'] = 200 if ok else 500
		response['statusReason'] = 'OK' if ok else 'Error'
		response['content-type'] = 'image/png'
		response['data'] = encoded.tobytes()
		return response
	if request.get('uri') == '/state':
		try:
			body = json.dumps(_snapshot())
			response['statusCode'] = 200
			response['statusReason'] = 'OK'
			response['content-type'] = 'application/json'
			response['data'] = body
		except Exception as e:
			response['statusCode'] = 500
			response['statusReason'] = 'Error'
			response['content-type'] = 'application/json'
			response['data'] = json.dumps({'error': str(e)})
		return response
	response['statusCode'] = 404
	response['statusReason'] = 'Not Found'
	response['data'] = 'Use /state'
	return response


def onWebSocketOpen(dat: webserverDAT, client: str, uri: str):
	return


def onWebSocketClose(dat: webserverDAT, client: str):
	return


def onWebSocketReceiveText(dat: webserverDAT, client: str, data: str):
	return


def onWebSocketReceiveBinary(dat: webserverDAT, client: str, data: bytes):
	return


def onWebSocketReceivePing(dat: webserverDAT, client: str, data: bytes):
	dat.webSocketSendPong(client, data=data)
	return


def onWebSocketReceivePong(dat: webserverDAT, client: str, data: bytes):
	return


def onServerStart(dat: webserverDAT):
	return


def onServerStop(dat: webserverDAT):
	return
