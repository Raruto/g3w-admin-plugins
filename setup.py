from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py
from setuptools.command.editable_wheel import editable_wheel


class BuildPy(build_py):
    def run(self):
        super().run()
        self.copy_file("g3w_plugins.pth", str(Path(self.build_lib) / "g3w_plugins.pth"))


class EditableWheel(editable_wheel):
    def _run_build_commands(self, dist_name, unpacked_wheel, build_lib, tmp_dir):
        outputs = super()._run_build_commands(dist_name, unpacked_wheel, build_lib, tmp_dir)
        self.copy_file("g3w_plugins.pth", str(Path(unpacked_wheel) / "g3w_plugins.pth"))
        return outputs


setup(cmdclass={"build_py": BuildPy, "editable_wheel": EditableWheel})
