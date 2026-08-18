import json
from pathlib import Path


class FakeContainer:
    def __init__(self, exit_code):
        self.exit_code = exit_code
        self.removed = False

    def wait(self, timeout=None):
        return {"StatusCode": self.exit_code}

    def logs(self, tail=None):
        return b"container said no"

    def remove(self, force=False):
        self.removed = True


class FakeDocker:
    """Just enough of the docker sdk: `images` and `containers` point back at this
    object, and run() writes into the bind-mounted dir the way a real container would."""

    def __init__(self, perf=None, exit_code=0, raw=None, build_error=None):
        self.perf, self.raw = perf, raw
        self.exit_code, self.build_error = exit_code, build_error
        self.built = []
        self.last_container = None
        self.images = self.containers = self

    def build(self, fileobj=None, tag=None, rm=False):
        if self.build_error:
            raise self.build_error
        self.built.append(tag)

    def run(self, image, detach=True, volumes=None):
        host_dir = Path(next(iter(volumes)))
        if self.raw is not None:
            (host_dir / "perf.json").write_text(self.raw)
        elif self.perf is not None:
            (host_dir / "perf.json").write_text(json.dumps({"perf": self.perf}))
        self.last_container = FakeContainer(self.exit_code)
        return self.last_container
