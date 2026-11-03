param(
    [Parameter(Mandatory = $true)][string]$TextFile,
    [Parameter(Mandatory = $true)][string]$OutputFile,
    [int]$Rate = 0,
    [string]$Voice = "Microsoft Huihui Desktop"
)

Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $synth.SelectVoice($Voice)
    $synth.Rate = $Rate
    $format = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(
        16000,
        [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,
        [System.Speech.AudioFormat.AudioChannel]::Mono
    )
    $synth.SetOutputToWaveFile($OutputFile, $format)
    $text = [System.IO.File]::ReadAllText($TextFile, [System.Text.Encoding]::UTF8)
    $synth.Speak($text)
}
finally {
    $synth.Dispose()
}
