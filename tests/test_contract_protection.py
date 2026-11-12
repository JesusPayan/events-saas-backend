
"""COM-02.1.11.4 - Regresion de proteccion contractual.

Pruebas aisladas: no conectan a MySQL ni modifican datos reales.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.services import contract_service as cs
from app.services import contract_protection_service as cps


TENANT_ID = 1
CONTRACT_ID = 1
DOCUMENT_ID = 10
USER_ID = 2


def make_contract(status="draft"):
    return SimpleNamespace(
        id=CONTRACT_ID,
        tenant_id=TENANT_ID,
        status=status,
        updated_at=None,
    )


def make_document(is_final=True):
    return SimpleNamespace(
        id=DOCUMENT_ID,
        tenant_id=TENANT_ID,
        contract_id=CONTRACT_ID,
        is_final=is_final,
    )


@pytest.mark.parametrize(
    "new_status",
    ["draft", "cancelled"],
)
def test_active_rejects_invalid_transitions(new_status):
    contract = make_contract("active")

    with (
        patch.object(
            cs.db.session, "scalar", return_value=contract
        ),
        patch.object(cs.db.session, "add") as add,
        patch.object(cs.db.session, "commit") as commit,
        patch.object(cs.db.session, "rollback") as rollback,
    ):
        with pytest.raises(cs.ContractError) as exc:
            cs.change_contract_status(
                tenant_id=TENANT_ID,
                contract_id=CONTRACT_ID,
                new_status=new_status,
                user_id=USER_ID,
            )

        assert exc.value.code == "invalid_status_transition"
        assert exc.value.status_code == 409
        assert contract.status == "active"
        add.assert_not_called()
        commit.assert_not_called()
        rollback.assert_called_once()


def test_active_can_be_completed():
    contract = make_contract("active")

    with (
        patch.object(
            cs.db.session, "scalar", return_value=contract
        ),
        patch.object(cs.db.session, "add") as add,
        patch.object(cs.db.session, "commit") as commit,
    ):
        result = cs.change_contract_status(
            tenant_id=TENANT_ID,
            contract_id=CONTRACT_ID,
            new_status="completed",
            user_id=USER_ID,
        )

        assert result.status == "completed"
        assert contract.status == "completed"
        add.assert_called_once()
        commit.assert_called_once()


@pytest.mark.parametrize(
    "status",
    ["active", "completed", "cancelled"],
)
def test_closed_contract_content_cannot_be_edited(status):
    contract = make_contract(status)

    with patch.object(
        cps, "lock_contract", return_value=contract
    ):
        with pytest.raises(cps.ContractProtectedError) as exc:
            cps.assert_contract_content_editable(
                tenant_id=TENANT_ID,
                contract_id=CONTRACT_ID,
            )

    assert exc.value.code == "contract_protected"
    assert exc.value.status_code == 409


def test_draft_with_final_document_cannot_be_edited():
    contract = make_contract("draft")

    with (
        patch.object(
            cps, "lock_contract", return_value=contract
        ),
        patch.object(
            cps, "has_final_document", return_value=True
        ),
    ):
        with pytest.raises(cps.ContractProtectedError):
            cps.assert_contract_content_editable(
                tenant_id=TENANT_ID,
                contract_id=CONTRACT_ID,
            )


def test_draft_with_signatures_cannot_be_edited():
    contract = make_contract("draft")

    with (
        patch.object(
            cps, "lock_contract", return_value=contract
        ),
        patch.object(
            cps, "has_final_document", return_value=False
        ),
        patch.object(
            cps, "has_registered_signatures", return_value=True
        ),
    ):
        with pytest.raises(cps.ContractProtectedError):
            cps.assert_contract_content_editable(
                tenant_id=TENANT_ID,
                contract_id=CONTRACT_ID,
            )


def test_final_document_cannot_be_modified():
    document = make_document(is_final=True)
    contract = make_contract("draft")

    with (
        patch.object(
            cps.db.session, "scalar", return_value=document
        ),
        patch.object(
            cps, "lock_contract", return_value=contract
        ),
    ):
        with pytest.raises(cps.ContractProtectedError) as exc:
            cps.assert_document_can_be_modified(
                tenant_id=TENANT_ID,
                document_id=DOCUMENT_ID,
            )

    assert exc.value.code == "document_protected"
    assert exc.value.status_code == 409


def test_signed_document_cannot_be_modified():
    document = make_document(is_final=False)
    contract = make_contract("draft")

    with (
        patch.object(
            cps.db.session,
            "scalar",
            side_effect=[document, 999],
        ),
        patch.object(
            cps, "lock_contract", return_value=contract
        ),
    ):
        with pytest.raises(cps.ContractProtectedError) as exc:
            cps.assert_document_can_be_modified(
                tenant_id=TENANT_ID,
                document_id=DOCUMENT_ID,
            )

    assert exc.value.code == "document_signed"
    assert exc.value.status_code == 409


def test_active_contract_cannot_create_invitation():
    contract = make_contract("active")

    with patch.object(
        cps, "lock_contract", return_value=contract
    ):
        with pytest.raises(cps.ContractProtectedError) as exc:
            cps.assert_new_invitation_allowed(
                tenant_id=TENANT_ID,
                contract_id=CONTRACT_ID,
                document_id=DOCUMENT_ID,
                signer_role="client",
            )

    assert exc.value.status_code == 409


def test_obsolete_document_cannot_be_signed():
    contract = make_contract("draft")
    document = make_document(is_final=True)

    with (
        patch.object(
            cps, "lock_contract", return_value=contract
        ),
        patch.object(
            cps.db.session,
            "scalar",
            side_effect=[document, 11],
        ),
    ):
        with pytest.raises(cps.ContractProtectedError) as exc:
            cps.assert_new_invitation_allowed(
                tenant_id=TENANT_ID,
                contract_id=CONTRACT_ID,
                document_id=DOCUMENT_ID,
                signer_role="client",
            )

    assert exc.value.code == "obsolete_document"
    assert exc.value.status_code == 409


def test_duplicate_active_invitation_is_rejected():
    contract = make_contract("draft")
    document = make_document(is_final=True)

    with (
        patch.object(
            cps, "lock_contract", return_value=contract
        ),
        patch.object(
            cps.db.session,
            "scalar",
            side_effect=[document, DOCUMENT_ID, 99],
        ),
    ):
        with pytest.raises(cps.ContractProtectedError) as exc:
            cps.assert_new_invitation_allowed(
                tenant_id=TENANT_ID,
                contract_id=CONTRACT_ID,
                document_id=DOCUMENT_ID,
                signer_role="client",
            )

    assert exc.value.code == "active_invitation_exists"
    assert exc.value.status_code == 409


def test_already_signed_role_cannot_be_invited():
    contract = make_contract("draft")
    document = make_document(is_final=True)

    with (
        patch.object(
            cps, "lock_contract", return_value=contract
        ),
        patch.object(
            cps.db.session,
            "scalar",
            side_effect=[
                document,
                DOCUMENT_ID,
                None,
                99,
            ],
        ),
    ):
        with pytest.raises(cps.ContractProtectedError) as exc:
            cps.assert_new_invitation_allowed(
                tenant_id=TENANT_ID,
                contract_id=CONTRACT_ID,
                document_id=DOCUMENT_ID,
                signer_role="provider",
            )

    assert exc.value.code == "signer_already_signed"
    assert exc.value.status_code == 409


def test_invalid_signer_role_is_rejected():
    with pytest.raises(ValueError):
        cps.assert_new_invitation_allowed(
            tenant_id=TENANT_ID,
            contract_id=CONTRACT_ID,
            document_id=DOCUMENT_ID,
            signer_role="administrator",
        )
