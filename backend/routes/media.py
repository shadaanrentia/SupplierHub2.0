"""Media proxy routes."""

import logging
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


@router.get("/media_proxy")
async def media_proxy(url: str):
    """Proxy supplier media requests so the frontend can display images."""

    if not url:
        raise HTTPException(
            status_code=400,
            detail="URL parameter is required"
        )

    # Domains that are allowed to be proxied.
    allowed_domains = [
        # SanMar Canada
        "media.sanmarcanada.com",
        "sanmarcanada.com",

        # ATC
        "cdn-atc.ca",
        "images.atc.ca",
        "atc.ca",

        # S&S Activewear
        "cdn.ssactivewear.com",
        "ssactivewear.com",

        # alphabroder
        "media.alphabroder.com",
        "alphabroder.com",
    ]

    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower().split(":")[0]

        # Only allow the domains explicitly listed above.
        is_allowed = any(
            domain == allowed or domain.endswith("." + allowed)
            for allowed in allowed_domains
        )

        if not is_allowed:
            raise HTTPException(
                status_code=403,
                detail=f"Domain not allowed: {domain}"
            )

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.sanmarcanada.com/",
        }

        async with httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            trust_env=False
        ) as client:

            response = await client.get(
                url,
                headers=headers
            )

            if response.status_code != 200:
                logger.error(
                    "Failed to fetch image from %s: HTTP %s",
                    url,
                    response.status_code
                )

                raise HTTPException(
                    status_code=response.status_code,
                    detail=(
                        f"Failed to fetch image: "
                        f"HTTP {response.status_code}"
                    )
                )

            content_type = response.headers.get(
                "content-type",
                "image/jpeg"
            )

            # Do not return an HTML error page as an image.
            if "text/html" in content_type.lower():
                raise HTTPException(
                    status_code=403,
                    detail=(
                        "Received HTML instead of image - "
                        "CDN may still be blocking"
                    )
                )

            logger.info(
                "Successfully proxied media: %s",
                url
            )

            return StreamingResponse(
                iter([response.content]),
                media_type=content_type,
                headers={
                    "Cache-Control": "public, max-age=86400",
                    "Access-Control-Allow-Origin": "*",
                },
            )

    except HTTPException:
        raise

    except httpx.RequestError as e:
        logger.error(
            "Media proxy request error for %s: %s",
            url,
            e
        )

        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch media: {str(e)}"
        )

    except Exception as e:
        logger.exception(
            "Unexpected media proxy error for %s",
            url
        )

        raise HTTPException(
            status_code=500,
            detail=f"Media proxy error: {str(e)}"
        )