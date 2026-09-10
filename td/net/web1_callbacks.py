"""webclientDAT callbacks -- REST bootstrap (DESIGN.md 5 step 10) and manual
Rescan (Shift+Device)."""
from typing import Dict, Any


def onConnect(dat: webclientDAT, id: int):
	return


def onDisconnect(dat: webclientDAT, id: int):
	return


def onResponse(dat: webclientDAT, statusCode: Dict[str, Any],
               headerDict: Dict[str, str], data: bytes, id: int):
	ext = parent.PushResolume
	if ext and ext.ResolumeState:
		ext.ResolumeState.OnResponse(data, id, ext,
			'' if statusCode['code'] == 200 else 'HTTP %s' % statusCode['code'])
	return


def onError(dat: webclientDAT, id: int, url: str, error: Exception):
	ext = parent.PushResolume
	ext.ResolumeState.OnResponse(b'', id, ext, str(error))
	debug(error)
