# One-command entry point for the voice-picking helper (Windows PowerShell).
#
# Example:
#   .\identify.ps1 call.webm -o output

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
}

docker compose run --rm identify @Args
