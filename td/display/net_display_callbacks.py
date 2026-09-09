"""TCP/IP DAT Callbacks for display/net_display -- forwards connection
lifecycle to Display (mod_display). No frame content is parsed here; the
helper process only ever receives, never sends anything we act on yet.
"""


def onConnect(dat, peer):
	ext = parent.PushResolume
	if ext and ext.Display:
		ext.Display.OnConnect()
	return


def onReceive(dat, rowIndex, message, bytes, peer):
	return


def onClose(dat, peer):
	ext = parent.PushResolume
	if ext and ext.Display:
		ext.Display.OnClose()
	return
