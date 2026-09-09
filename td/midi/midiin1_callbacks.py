"""
MIDI In DAT Callbacks -- routes decoded events to Surface.OnReceiveMIDI (T9:
logic runs directly here, never through a coalescing custom parameter).

Root cause (confirmed live 2026-08-14, see PHASE3A_FINDINGS.md 7): this is
NOT a Push 2 hardware quirk. TouchDesigner's MIDI In DAT displays/reports
CC and note numbers 1-indexed, while Ableton's Push2-map.json/MidiMapping.png
use the raw 0-indexed decimal on the wire -- raw 71 is reported as 72. So
event.index is always exactly one higher than the spec, uniformly across
notes AND CCs. One global -1 correction on every incoming index, rather
than per-range special cases. Pitch bend (touch strip) has no index to
correct -- it's a fixed sentinel (12) matched against a single CSV row.
"""

_TYPE_MAP = {
	'Note On': 'note', 'Note Off': 'note',
	'Control Change': 'cc',
	'Pitch Bend': 'pitchbend',
	'Pitch Bend Change': 'pitchbend',
}


def onReceiveMIDI(dat: midiinDAT, event: MIDIEvent):
	ext = parent.PushResolume
	surface = ext.Surface if ext else None
	if surface is None:
		return
	in_type = _TYPE_MAP.get(event.message)
	if in_type is None:
		return
	if event.message == 'Note Off':
		return  # pads are one-shot triggers; release carries no signal here
	if in_type == 'pitchbend':
		number = 12
		value = event.value14
	else:
		number = event.index - 1
		value = event.value
	surface.OnReceiveMIDI(in_type, number, event.channel, value, ext)
	return
