from fastapi import HTTPException
from ..db import Database, User


async def delete_account(db: Database, user: User):
    # Deletes happen before deleting the account: otherwise its documents become orphaned.
    for bucket in ("resumes", "profile-photos"):
        for _ in range(100):
            objects = await db.request("POST", f"/storage/v1/object/list/{bucket}", json={"prefix": user.id + "/", "limit": 100, "offset": 0})
            if not objects:
                break
            if any(not item.get("id") for item in objects):
                raise HTTPException(409, "Hay carpetas inesperadas en el almacenamiento. La eliminación necesita revisión.")
            prefixes = [f"{user.id}/{item['name']}" for item in objects]
            await db.request("DELETE", f"/storage/v1/object/{bucket}", json={"prefixes": prefixes})
        else:
            raise HTTPException(409, "La eliminación de documentos no terminó. Volvé a intentarlo antes de borrar la cuenta.")
    await db.request("DELETE", f"/auth/v1/admin/users/{user.id}", json={"should_soft_delete": False})
    return {"deleted": True, "message": "Se eliminó la cuenta, sus datos y documentos privados. Podés quitar también el acceso de Trabajo YA en la configuración de tu cuenta de Google."}
