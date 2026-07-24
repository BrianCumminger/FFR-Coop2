@echo off
REM Valid options are: gui_onefile, cli_onefile, both_onedir
set BUILD_TYPE=%1
if "%BUILD_TYPE%"=="" set BUILD_TYPE=gui_onefile

echo Deleting old dist folder...
if exist dist rmdir /s /q dist

echo Starting PyInstaller with configuration: %BUILD_TYPE%
pyinstaller --clean build.spec

echo Copying bizhawk-connector to dist...
xcopy /E /I /Y bizhawk-connector dist\bizhawk-connector