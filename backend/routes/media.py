"""Media proxy routes."""
import logging
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
import httpx

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


@router.get("/media_proxy")
async def media_proxy(url: str):
    if not url:
        raise HTTPException(400, "URL parameter is required")
    allowed_domains = [
        'cdn-atc.ca', 'cdn.ssactivewear.com', 'media.alphabroder.com',
        'images.atc.ca', 'atc.ca', 'ssactivewear.com', 'alphabroder.com',
        'www.atc.ca', 'www.ssactivewear.com', 'www.alphabroder.com'
    ]
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        is_allowed = any(allowed in domain for allowed in allowed_domains)
        if not is_allowed:
            raise HTTPException(403, f"Domain not allowed: {domain}")
        async with httpx.AsyncClient(timeout=30.0) as client:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'image/*,*/*;q=0.8', 'Accept-Language': 'en-US,en;q=0.9', 'Referer': f'https://{domain}/',
            }
            response = await client.get(url, headers=headers, follow_redirects=True)
            if response.status_code != 200:
                raise HTTPException(response.status_code, f"Failed to fetch image: HTTP {response.status_code}")
            content_type = response.headers.get('content-type', 'image/jpeg')
            if 'text/html' in content_type:
                raise HTTPException(403, "Received HTML instead of image - CDN may still be blocking")
            return StreamingResponse(iter([response.content]), media_type=content_type,
                headers={'Cache-Control': 'public, max-age=86400', 'Access-Control-Allow-Origin': '*'})
    except httpx.RequestError as e:
        logger.error(f"Media proxy error: {e}")
        raise HTTPException(500, f"Failed to fetch media: {str(e)}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Media proxy error: {e}")
        raise HTTPException(500, f"Media proxy error: {str(e)}")
