"""exec_boot: the ONLY startup entry point (DESIGN.md T8). Deferred by
delayFrames=15 because CoreMIDI enumeration is not guaranteed complete at
onStart (DESIGN.md 5)."""


def onStart():
	run("parent.PushResolume.Boot()", delayFrames=15)
	return


def onCreate():
	return


def onExit():
	parent.PushResolume.CloseProject()
	return


def onFrameStart(frame):
	return


def onFrameEnd(frame):
	return


def onPlayStateChange(state):
	return


def onDeviceChange():
	run("parent.PushResolume.Boot()", delayFrames=15)
	return


def onProjectPreSave():
	return


def onProjectPostSave():
	return
