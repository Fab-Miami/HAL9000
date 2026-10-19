import re
import urllib.request
import urllib.error
from html.parser import HTMLParser
from .tool_events import notify_tool_execution

class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text = []
        self.ignore = False

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'noscript', 'svg', 'iframe'):
            self.ignore = True
        elif tag in ('p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li', 'div', 'br', 'tr', 'article', 'section'):
            self.text.append('\n')

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'noscript', 'svg', 'iframe'):
            self.ignore = False
        elif tag in ('p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li', 'div', 'tr', 'article', 'section'):
            self.text.append('\n')

    def handle_data(self, data):
        if not self.ignore:
            t = data.strip()
            if t:
                self.text.append(t + ' ')

def read_web_page(url: str) -> str:
    """
    Directly navigates to, fetches, and reads the clean text content of a specific web page or URL.
    Use this tool whenever Fab asks you to visit, inspect, read, check, or browse a website or link
    (for example 'colozzi.com', 'https://colozzi.com', or any other web address).
    
    Args:
        url: The web address or domain to visit (e.g., 'colozzi.com' or 'https://colozzi.com').
    
    Returns:
        The extracted readable text content of the web page.
    """
    notify_tool_execution("browse")
    
    if not url:
        return "Error: No URL provided."
    
    clean_url = url.strip()
    if not clean_url.startswith(('http://', 'https://')):
        clean_url = 'https://' + clean_url
        
    print(f"🌐 [WebBrowser] Fetching web page: {clean_url}", flush=True)
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
    }
    
    try:
        req = urllib.request.Request(clean_url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            content_type = resp.headers.get('content-type', '').lower()
            raw_bytes = resp.read(500000) # Read up to 500KB
            
            # Detect charset
            charset = 'utf-8'
            if 'charset=' in content_type:
                charset = content_type.split('charset=')[-1].split(';')[0].strip()
                
            try:
                html = raw_bytes.decode(charset, errors='replace')
            except Exception:
                html = raw_bytes.decode('utf-8', errors='replace')
                
        parser = TextExtractor()
        parser.feed(html)
        
        raw_text = ''.join(parser.text)
        # Collapse multiple spaces and excessive blank lines
        clean_text = re.sub(r'[ \t]+', ' ', raw_text)
        clean_text = re.sub(r'\n\s*\n', '\n', clean_text).strip()
        
        # Cap text at 8,000 characters to stay concise and token-efficient
        if len(clean_text) > 8000:
            clean_text = clean_text[:8000] + "\n\n... [Content truncated for brevity] ..."
            
        print(f"✅ [WebBrowser] Successfully extracted {len(clean_text)} characters from {clean_url}.", flush=True)
        return clean_text
        
    except urllib.error.HTTPError as e:
        msg = f"Failed to load {clean_url}: HTTP error {e.code} ({e.reason})"
        print(f"⚠️ [WebBrowser] {msg}", flush=True)
        return msg
    except urllib.error.URLError as e:
        # Fallback to http if https failed
        if clean_url.startswith('https://'):
            http_url = 'http://' + clean_url[8:]
            try:
                print(f"🔄 [WebBrowser] HTTPS failed, trying HTTP: {http_url}", flush=True)
                req = urllib.request.Request(http_url, headers=headers)
                with urllib.request.urlopen(req, timeout=10) as resp:
                    raw_bytes = resp.read(500000)
                    html = raw_bytes.decode('utf-8', errors='replace')
                parser = TextExtractor()
                parser.feed(html)
                clean_text = re.sub(r'[ \t]+', ' ', ''.join(parser.text))
                return re.sub(r'\n\s*\n', '\n', clean_text).strip()[:8000]
            except Exception:
                pass
        msg = f"Failed to reach {clean_url}: {e.reason}"
        print(f"⚠️ [WebBrowser] {msg}", flush=True)
        return msg
    except Exception as e:
        msg = f"Error reading {clean_url}: {str(e)}"
        print(f"⚠️ [WebBrowser] {msg}", flush=True)
        return msg
