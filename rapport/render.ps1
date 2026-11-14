param([string]$Docx, [string]$Pdf, [string]$PngDir = "")
# Opens the document read-only in Word, reports the page count, exports a PDF preview and,
# when -PngDir is given, one PNG per page (from Word's own page metafiles).
Add-Type -AssemblyName System.Drawing
$word = New-Object -ComObject Word.Application
$word.Visible = $false
$word.DisplayAlerts = 0
try {
    $doc = $word.Documents.Open($Docx, $false, $true)
    $pages = $doc.ComputeStatistics(2)
    $words = $doc.ComputeStatistics(0)
    "pages=$pages words=$words"
    $doc.ExportAsFixedFormat($Pdf, 17)
    if ($PngDir -ne "") {
        New-Item -ItemType Directory -Force $PngDir | Out-Null
        Get-ChildItem $PngDir -Filter "page-*.png" | Remove-Item -Force
        $doc.ActiveWindow.View.Type = 3
        $pane = $doc.ActiveWindow.Panes.Item(1)
        for ($i = 1; $i -le $pane.Pages.Count; $i++) {
            $bits = $pane.Pages.Item($i).EnhMetaFileBits
            $stream = New-Object System.IO.MemoryStream(, [byte[]]$bits)
            $meta = New-Object System.Drawing.Imaging.Metafile($stream)
            $w = 1020; $h = 1320
            $bmp = New-Object System.Drawing.Bitmap($w, $h)
            $g = [System.Drawing.Graphics]::FromImage($bmp)
            $g.Clear([System.Drawing.Color]::White)
            $g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
            $g.DrawImage($meta, 0, 0, $w, $h)
            $bmp.Save((Join-Path $PngDir ("page-{0:d2}.png" -f $i)), [System.Drawing.Imaging.ImageFormat]::Png)
            $g.Dispose(); $bmp.Dispose(); $meta.Dispose(); $stream.Dispose()
        }
    }
    $doc.Close($false)
} finally {
    $word.Quit()
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($word) | Out-Null
}
