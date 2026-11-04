
from sqlalchemy import select

from app import create_app
from app.extensions import db
from app.models.identity import (
    Permission,
    Role,
    RolePermission
)

PERMISSIONS = (
    "events.read",
    "events.create",
    "events.update"
)


def seed():
    permissions = {}

    for code in PERMISSIONS:
        permission = db.session.scalar(
            select(Permission).where(Permission.code == code)
        )

        if permission is None:
            permission = Permission(code=code)
            db.session.add(permission)
            db.session.flush()

        permissions[code] = permission

    owner_roles = db.session.scalars(
        select(Role).where(Role.name == "owner")
    ).all()

    for role in owner_roles:
        for permission in permissions.values():
            exists = db.session.scalar(
                select(RolePermission).where(
                    RolePermission.role_id == role.id,
                    RolePermission.permission_id == permission.id
                )
            )

            if exists is None:
                db.session.add(
                    RolePermission(
                        role_id=role.id,
                        permission_id=permission.id
                    )
                )

    db.session.commit()
    print("Permisos de eventos registrados correctamente.")


if __name__ == "__main__":
    app = create_app()

    with app.app_context():
        seed()
