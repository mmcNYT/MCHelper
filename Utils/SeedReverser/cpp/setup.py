from setuptools import setup, Extension

setup(
    name="_jigsaw_engine",
    ext_modules=[
        Extension("_jigsaw_engine", ["jigsaw_engine.cpp"],
                  language="c++", extra_compile_args=["/O2", "/std:c++17", "/utf-8"])
    ],
)