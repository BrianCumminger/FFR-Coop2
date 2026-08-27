@echo off
setlocal
echo Deleting old dist folder...
if exist dist rmdir /s /q dist

echo Building with PyInstaller...
pyinstaller --clean build.spec

echo Copying bizhawk-connector to dist...
xcopy /E /I /Y bizhawk-connector dist\bizhawk-connector

set "PATH=%~dp0;%PATH%"

echo Extracting version from main.py...
for /f "delims=" %%I in ('python -c "import re; print(re.search(r'VERSION\s*=\s*\x22([^\x22]+)\x22', open('main.py').read()).group(1))"') do set "VERSION=%%I"
echo Building version: %VERSION%

cd dist
7z a FFR-Coop-%VERSION%-Windows.zip * -x!config.ini
cd ..
endlocal