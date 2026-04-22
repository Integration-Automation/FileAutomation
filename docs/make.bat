@ECHO OFF
pushd %~dp0

REM Minimal Sphinx build script for Windows

if "%SPHINXBUILD%" == "" (
	set SPHINXBUILD=sphinx-build
)
set SOURCEDIR=source
set BUILDDIR=_build

if "%1" == "" goto help

%SPHINXBUILD% >NUL 2>NUL
if errorlevel 9009 (
	echo.
	echo.sphinx-build was not found. Install it with: pip install -r requirements.txt
	exit /b 1
)

if "%1" == "html-zh-TW" goto build-zh-TW
if "%1" == "html-zh-CN" goto build-zh-CN
if "%1" == "html-all" goto build-all

%SPHINXBUILD% -M %1 %SOURCEDIR% %BUILDDIR% %SPHINXOPTS% %O%
goto end

:build-zh-TW
%SPHINXBUILD% -b html source.zh-TW %BUILDDIR%\html-zh-TW %SPHINXOPTS% %O%
goto end

:build-zh-CN
%SPHINXBUILD% -b html source.zh-CN %BUILDDIR%\html-zh-CN %SPHINXOPTS% %O%
goto end

:build-all
%SPHINXBUILD% -M html %SOURCEDIR% %BUILDDIR% %SPHINXOPTS% %O%
%SPHINXBUILD% -b html source.zh-TW %BUILDDIR%\html-zh-TW %SPHINXOPTS% %O%
%SPHINXBUILD% -b html source.zh-CN %BUILDDIR%\html-zh-CN %SPHINXOPTS% %O%
goto end

:help
%SPHINXBUILD% -M help %SOURCEDIR% %BUILDDIR% %SPHINXOPTS% %O%

:end
popd
