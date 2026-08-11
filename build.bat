@echo off
setlocal
echo Deleting old dist folder...
if exist dist rmdir /s /q dist

echo Building with PyInstaller...
pyinstaller --clean build.spec

echo Copying bizhawk-connector to dist...
xcopy /E /I /Y bizhawk-connector dist\bizhawk-connector

set "PATH=%~dp0;%PATH%"
cd dist
7z a coop2.zip * -x!config.ini
cd ..
endlocal