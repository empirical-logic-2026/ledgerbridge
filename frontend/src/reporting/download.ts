// Saves text as a file in the browser (CSV exports). A BOM first, so Excel reads UTF-8.

export function download(name: string, text: string): void {
  const url = URL.createObjectURL(new Blob(['\ufeff', text], { type: 'text/csv;charset=utf-8' }))
  const link = document.createElement('a')
  link.href = url
  link.download = name
  link.click()
  URL.revokeObjectURL(url)
}
