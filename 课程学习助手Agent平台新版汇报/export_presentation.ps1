param(
    [Parameter(Mandatory = $true)][string]$PptPath,
    [Parameter(Mandatory = $true)][string]$PdfPath,
    [Parameter(Mandatory = $true)][string]$Slide10PngPath
)

$ErrorActionPreference = "Stop"
$powerPoint = New-Object -ComObject PowerPoint.Application

try {
    $presentation = $powerPoint.Presentations.Open($PptPath, $true, $false, $false)
    $presentation.SaveAs($PdfPath, 32)
    $presentation.Slides.Item(10).Export($Slide10PngPath, "PNG", 1600, 900)
    $previewDir = [System.IO.Path]::GetDirectoryName($Slide10PngPath)
    $presentation.Slides.Item(15).Export(
        [System.IO.Path]::Combine($previewDir, "slide15-check.png"), "PNG", 1600, 900
    )
    $presentation.Slides.Item(22).Export(
        [System.IO.Path]::Combine($previewDir, "slide22-check.png"), "PNG", 1600, 900
    )
    $presentation.Close()
}
finally {
    $powerPoint.Quit()
}
