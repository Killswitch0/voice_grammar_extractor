# One-command entry point (Windows PowerShell). Builds the image on first use,
# then just runs it. Everything after the script name is passed straight to main.py.
#
# Examples:
#   .\run.ps1 call.webm --reference my_voice.wav
#   .\run.ps1 monologue.mp4 --no-diarization

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
}

docker compose run --rm extractor @Args
