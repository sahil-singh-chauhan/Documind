import re

def extract_doc_fields(d):
    """Extract (metadata, page_content) from a LangChain Document or raw dict."""
    if hasattr(d, 'metadata'):
        return d.metadata, d.page_content
    if isinstance(d, dict) and 'document' in d:
        nd = d['document']
        if hasattr(nd, 'metadata'):
            return nd.metadata, nd.page_content
        return nd.get('metadata', {}), nd.get('page_content', nd.get('text', ''))
    return d.get('metadata', {}), d.get('page_content', d.get('text', ''))


def clean_snippet_text(text: str) -> str:
    """Remove boilerplate marketing lines and normalise whitespace."""
    patterns = [
        r"(?im)^\s*Scan to Download.*$",
        r"(?im)^\s*Written by .*$",
        r"(?im)^\s*Listen .*Audiobook.*$",
        r"(?im)^\s*About the book.*$",
        r"(?im)^\s*Check more about .*$",
        r"(?im)^\s*Key Point:.*$",
        r"(?im)^\s*inspiration\s*$",
    ]
    for pat in patterns:
        text = re.sub(pat, "", text)
    lines = [re.sub(r"^[\-•\*\s]+", "", ln).strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if len(ln) > 2]
    cleaned = "\n".join(lines)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned


def clean_output(output_string: str) -> str:
    """Format and clean the LLM's final string response."""
    formatted_output = output_string.replace('\n\n', '\n')
    lines = formatted_output.split('\n')
    processed_lines = []
    for line in lines:
        processed_line = line.lstrip('* ').strip()
        processed_lines.append(processed_line)
    final_output = '\n'.join(processed_lines)
    return final_output
