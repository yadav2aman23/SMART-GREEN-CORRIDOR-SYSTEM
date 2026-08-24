from fastapi import Header, HTTPException

DEVICE_API_KEY = "srWNbEMmCIAI_u8Tm-qJ8LcAn3B1rP1BTAcQwvv_zKA"


def verify_device(
    x_device_key: str | None = Header(default=None)
):

    if x_device_key != DEVICE_API_KEY:
        raise HTTPException(
            status_code=401,
            detail="Invalid device authentication"
        )

    return True
