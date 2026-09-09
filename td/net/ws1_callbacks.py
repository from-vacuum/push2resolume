"""WebSocket DAT Callbacks -- routes composition/typed messages to
ResolumeState.OnMessage, which triggers FxRegistry.Rebuild on structural
change (DESIGN.md 4.5)."""


def onConnect(dat: websocketDAT):
	ext = parent.PushResolume
	if ext and ext.ResolumeState:
		ext.ResolumeState.Connected = True
		ext.Health['resolume_state'] = True
		if ext.PushIO:
			ext.ResolumeState.Request(ext)
	return


def onDisconnect(dat: websocketDAT):
	ext = parent.PushResolume
	if ext and ext.ResolumeState:
		ext.ResolumeState.Connected = False
		ext.Health['resolume_state'] = False
	run("args[0].par.active = 0; args[0].par.active = 1", dat, delayFrames=90)
	return


def onReceiveText(dat: websocketDAT, rowIndex: int, message: str):
	ext = parent.PushResolume
	if ext and ext.ResolumeState:
		ext.ResolumeState.Connected = True
		ext.ResolumeState.OnMessage(message, ext)
	return


def onReceiveBinary(dat: websocketDAT, contents: bytes):
	return


def onReceivePing(dat: websocketDAT, contents: bytes):
	dat.sendPong(contents)
	return


def onReceivePong(dat: websocketDAT, contents: bytes):
	return


def onMonitorMessage(dat: websocketDAT, message: str):
	return
