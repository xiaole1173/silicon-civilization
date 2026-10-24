param(
    [Parameter(Mandatory=$true)][string]$TextFile,
    [Parameter(Mandatory=$true)][string]$OutFile,
    [string]$VoiceName = "Microsoft Kangkang",
    [int]$Rate = 0
)
Add-Type -AssemblyName System.Speech
$text = Get-Content -LiteralPath $TextFile -Raw -Encoding UTF8
if ([string]::IsNullOrWhiteSpace($text)) { exit 2 }
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
try { $synth.SelectVoice($VoiceName) } catch { }
$synth.Rate = $Rate
$synth.SetOutputToWaveFile($OutFile)
$synth.Speak($text)
$synth.Dispose()
Write-Output "ok"
