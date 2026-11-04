
from sqlalchemy import select

from app import create_app
from app.extensions import db
from app.models.identity import (
    Permission,
    Role,
    RolePermission
)

PERMISSIONS = [
    "inventory.read",
    "inventory.create",
    "inventory.update"
]


def seed_permissions():
    app = create_app()

    with app.app_context():
        for code in PERMISSIONS:
            permission = db.session.scalar(
                select(Permission).where(
                    Permission.code == code
                )
            )

            if permission is None:
                permission = Permission(code=code)
                db.session.add(permission)

        db.session.flush()

        owners = db.session.scalars(
            select(Role).where(Role.name == "owner")
        ).all()

        if not owners:
            db.session.rollback()
            print("No se encontraron roles owner.")
            return

        for role in owners:
            for code in PERMISSIONS:
                permission = db.session.scalar(
                    select(Permission).where(
                        Permission.code == code
                    )
                )

                existing = db.session.scalar(
                    select(RolePermission).where(
                        RolePermission.role_id == role.id,
                        RolePermission.permission_id == permission.id
                    )
                )

                if existing is None:
                    db.session.add(
                        RolePermission(
                            role_id=role.id,
                            permission_id=permission.id
                        )
                    )

        db.session.commit()

        print("Permisos de inventario asignados correctamente.")
        print(f"Roles owner actualizados: {len(owners)}")


if __name__ == "__main__":
    seed_permissions()
