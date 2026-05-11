from weasyprint import HTML
def to_pdf(html, out): HTML(string=html).write_pdf(out)

