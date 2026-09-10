"""Temporary main-thread instrumentation, injected by Envoy; never a TD DAT.

No operator is created, no DAT is edited, and all wrapped methods are restored.
Baseline timers measure inclusive wall and current-thread CPU time. cProfile
runs separately, across natural TD callbacks, so its overhead can be measured.
"""
import cProfile
import functools
import pstats
import sys
import time


class ProfileSession:
    def __init__(self, root_path, seconds=20):
        self.root_path = root_path
        self.seconds = seconds
        self.stage = 'starting'
        self.patches = []
        self.samples = {'baseline': {}, 'profile': {}}
        self.phases = {}
        self.profiler = cProfile.Profile()
        self.error = ''
        self.restored = False
        self.frame_samples = {'baseline': [], 'profile': []}

    def context(self):
        root = opex(self.root_path)
        return dict(project=project.name, frame=int(absTime.frame),
                    wall=time.perf_counter(), thread_cpu=time.thread_time(),
                    process_cpu=time.process_time(), display=root.Display.mode,
                    grid=root.Surface.GridMode, health=dict(root.Health))

    def wrap(self, target, name, label):
        original = getattr(target, name)
        session = self

        @functools.wraps(original)
        def measured(*args, **kwargs):
            stage = session.stage
            if stage not in session.samples:
                return original(*args, **kwargs)
            wall = time.perf_counter_ns()
            cpu = time.thread_time_ns()
            try:
                return original(*args, **kwargs)
            finally:
                cpu_ms = (time.thread_time_ns() - cpu) / 1e6
                wall_ms = (time.perf_counter_ns() - wall) / 1e6
                rows = session.samples[stage].setdefault(label, [])
                if len(rows) < 20000:
                    rows.append([wall_ms, cpu_ms])

        setattr(target, name, measured)
        self.patches.append((target, name, original, measured))

    def start(self):
        if sys.getprofile() is not None:
            raise RuntimeError('A Python profiler is already active')
        root = opex(self.root_path)
        try:
            targets = [
                (type(root.ext.PushResolume), ('Tick', 'CheckHealth', 'FullRedraw', '_pollTick')),
                (type(root.Display), ('SendPreviewFrame', 'SendTextFrame', 'SendFrame', 'RefreshDebugPreview')),
                (type(root.ResolumeState), ('OnResponse', 'OnMessage', '_normaliseFromComposition')),
                (type(root.FxRegistry), ('Rebuild', '_savePins')),
                (type(root.ResolumeOut), ('FlushOSC', 'FlushWS')),
                (type(root.PushIO), ('FlushLeds',)),
                (type(root.Surface), ('OnReceiveMIDI',)),
            ]
            for target, names in targets:
                for name in names:
                    self.wrap(target, name, target.__name__ + '.' + name)
            for path, names in [
                ('logic/mod_ledpainter', ('Paint', 'Snapshot')),
                ('display/mod_display', ('BuildFrameFromRGBA', 'RenderLCD')),
                ('net/webserver1_callbacks', ('onHTTPRequest',)),
                ('logic/exec_tick', ('onFrameStart',)),
            ]:
                for name in names:
                    self.wrap(root.op(path).module, name, path + '.' + name)
            self.begin_phase('baseline')
            run(self.sample, delayFrames=1)
            # Independent cleanup callback in case sampling is interrupted.
            run(self.stop, delayMilliSeconds=(self.seconds * 2 + 15) * 1000)
        except Exception:
            self.stop()
            raise
        return dict(stage=self.stage, seconds_per_phase=self.seconds, patches=len(self.patches))

    def begin_phase(self, stage):
        self.stage = stage
        self.phases[stage] = {'start': self.context()}
        self.deadline = time.perf_counter() + self.seconds
        if stage == 'profile':
            self.profiler.enable()

    def sample(self):
        if self.stage == 'done':
            return
        try:
            now = time.perf_counter()
            self.frame_samples[self.stage].append([int(absTime.frame), now])
            if now >= self.deadline:
                if self.stage == 'baseline':
                    self.phases['baseline']['end'] = self.context()
                    self.begin_phase('profile')
                else:
                    self.stop()
                    return
            run(self.sample, delayFrames=1)
        except Exception as error:
            self.error = repr(error)
            self.stop()

    def stop(self):
        if self.stage == 'done':
            return
        self.profiler.disable()
        if self.stage in self.phases and 'end' not in self.phases[self.stage]:
            self.phases[self.stage]['end'] = self.context()
        for target, name, original, measured in reversed(self.patches):
            if getattr(target, name) is measured:
                setattr(target, name, original)
        self.restored = all(getattr(t, n) is not m for t, n, o, m in self.patches)
        self.stage = 'done'

    def result(self):
        if self.stage != 'done':
            return dict(stage=self.stage, elapsed=self.seconds - max(0, self.deadline - time.perf_counter()))
        stats = pstats.Stats(self.profiler)
        rows = []
        for (filename, line, function), (primitive, calls, own, cumulative, callers) in stats.stats.items():
            rows.append(dict(file=filename, line=line, function=function,
                             primitive_calls=primitive, calls=calls,
                             self_ms=own * 1000, cumulative_ms=cumulative * 1000,
                             callers=[dict(file=k[0], line=k[1], function=k[2], stats=v)
                                      for k, v in callers.items()]))
        return dict(stage=self.stage, error=self.error, restored=self.restored,
                    phases=self.phases, samples=self.samples,
                    frame_samples=self.frame_samples,
                    cprofile=sorted(rows, key=lambda r: r['cumulative_ms'], reverse=True),
                    profile_self_ms=stats.total_tt * 1000,
                    profile_total_calls=stats.total_calls)


def start(root_path, seconds=20):
    import types
    previous = sys.modules.get('_push2_profile_session')
    if previous and previous.session.stage != 'done':
        raise RuntimeError('A profiling session is already running')
    holder = types.ModuleType('_push2_profile_session')
    holder.session = ProfileSession(root_path, seconds)
    sys.modules[holder.__name__] = holder
    return holder.session.start()


class JsonGCSession:
    """Observe JSON parsing and overlapping garbage collections without changing GC."""
    def __init__(self, seconds=20):
        import gc
        import json
        import threading
        self.gc = gc
        self.json = json
        self.threading = threading
        self.thread = threading.get_ident()
        self.seconds = seconds
        self.rows = []
        self.collections = []
        self.starts = {}
        self.original = json.loads
        self.active = False

    def on_gc(self, phase, info):
        if self.threading.get_ident() != self.thread:
            return
        now = time.perf_counter()
        generation = info['generation']
        if phase == 'start':
            self.starts[generation] = now
        else:
            began = self.starts.pop(generation, now)
            self.collections.append(dict(start=began, end=now, generation=generation,
                                         ms=(now - began) * 1000,
                                         collected=info.get('collected', 0)))

    def start(self):
        session = self

        @functools.wraps(self.original)
        def parse(*args, **kwargs):
            if session.threading.get_ident() != session.thread:
                return session.original(*args, **kwargs)
            began = time.perf_counter()
            cpu = time.thread_time()
            first_collection = len(session.collections)
            try:
                return session.original(*args, **kwargs)
            finally:
                ended = time.perf_counter()
                payload = args[0] if args else kwargs.get('s', '')
                session.rows.append(dict(start=began, end=ended,
                                         input_length=len(payload),
                                         wall_ms=(ended - began) * 1000,
                                         cpu_ms=(time.thread_time() - cpu) * 1000,
                                         gc=session.collections[first_collection:]))

        self.wrapper = parse
        self.gc_callback = self.on_gc
        self.start_time = time.perf_counter()
        self.gc.callbacks.append(self.gc_callback)
        self.json.loads = parse
        self.active = True
        run(self.stop, delayMilliSeconds=self.seconds * 1000)
        return dict(stage='json_gc', seconds=self.seconds)

    def stop(self):
        if not self.active:
            return
        if self.json.loads is self.wrapper:
            self.json.loads = self.original
        if self.gc_callback in self.gc.callbacks:
            self.gc.callbacks.remove(self.gc_callback)
        self.end_time = time.perf_counter()
        self.active = False

    def result(self):
        return dict(active=self.active, duration=(time.perf_counter() if self.active else self.end_time) - self.start_time,
                    restored=not self.active and self.json.loads is self.original,
                    rows=self.rows, collections=self.collections)
