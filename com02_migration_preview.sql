CREATE TABLE alembic_version (
    version_num VARCHAR(32) NOT NULL, 
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

-- Running upgrade  -> 0001_create_tenants

CREATE TABLE tenants (
    id BIGINT NOT NULL AUTO_INCREMENT, 
    name VARCHAR(180) NOT NULL, 
    slug VARCHAR(100) NOT NULL, 
    status VARCHAR(30) NOT NULL, 
    timezone VARCHAR(64) NOT NULL, 
    created_at DATETIME NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT uq_tenants_slug UNIQUE (slug)
);

INSERT INTO alembic_version (version_num) VALUES ('0001_create_tenants');

-- Running upgrade 0001_create_tenants -> 0002_identity

CREATE TABLE users (
    id BIGINT NOT NULL AUTO_INCREMENT, 
    email VARCHAR(254) NOT NULL, 
    password_hash VARCHAR(255) NOT NULL, 
    is_active BOOL NOT NULL, 
    created_at DATETIME NOT NULL, 
    PRIMARY KEY (id), 
    UNIQUE (email)
);

CREATE TABLE roles (
    id BIGINT NOT NULL AUTO_INCREMENT, 
    tenant_id BIGINT NOT NULL, 
    name VARCHAR(60) NOT NULL, 
    PRIMARY KEY (id), 
    UNIQUE (tenant_id, name), 
    UNIQUE (tenant_id, id), 
    FOREIGN KEY(tenant_id) REFERENCES tenants (id)
);

CREATE TABLE permissions (
    id BIGINT NOT NULL AUTO_INCREMENT, 
    code VARCHAR(100) NOT NULL, 
    PRIMARY KEY (id), 
    UNIQUE (code)
);

CREATE TABLE role_permissions (
    role_id BIGINT NOT NULL, 
    permission_id BIGINT NOT NULL, 
    PRIMARY KEY (role_id, permission_id), 
    FOREIGN KEY(role_id) REFERENCES roles (id) ON DELETE CASCADE, 
    FOREIGN KEY(permission_id) REFERENCES permissions (id) ON DELETE CASCADE
);

CREATE TABLE memberships (
    id BIGINT NOT NULL AUTO_INCREMENT, 
    tenant_id BIGINT NOT NULL, 
    user_id BIGINT NOT NULL, 
    role_id BIGINT NOT NULL, 
    status VARCHAR(20) NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(tenant_id, role_id) REFERENCES roles (tenant_id, id), 
    UNIQUE (tenant_id, user_id), 
    FOREIGN KEY(tenant_id) REFERENCES tenants (id), 
    FOREIGN KEY(user_id) REFERENCES users (id)
);

UPDATE alembic_version SET version_num='0002_identity' WHERE alembic_version.version_num = '0001_create_tenants';

-- Running upgrade 0002_identity -> 07b0444c6490

CREATE TABLE clients (
    id BIGINT NOT NULL AUTO_INCREMENT, 
    tenant_id BIGINT NOT NULL, 
    client_type VARCHAR(20) NOT NULL, 
    first_name VARCHAR(100) NOT NULL, 
    last_name VARCHAR(150), 
    business_name VARCHAR(180), 
    email VARCHAR(180), 
    phone VARCHAR(30), 
    whatsapp VARCHAR(30), 
    address VARCHAR(255), 
    city VARCHAR(100), 
    state VARCHAR(100), 
    postal_code VARCHAR(15), 
    notes TEXT, 
    status VARCHAR(20) NOT NULL, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(tenant_id) REFERENCES tenants (id)
);

CREATE INDEX ix_clients_tenant_email ON clients (tenant_id, email);

CREATE INDEX ix_clients_tenant_id ON clients (tenant_id);

CREATE INDEX ix_clients_tenant_status ON clients (tenant_id, status);

UPDATE alembic_version SET version_num='07b0444c6490' WHERE alembic_version.version_num = '0002_identity';

-- Running upgrade 07b0444c6490 -> 3a5716a4896f

CREATE TABLE events (
    id BIGINT NOT NULL AUTO_INCREMENT, 
    tenant_id BIGINT NOT NULL, 
    client_id BIGINT NOT NULL, 
    name VARCHAR(180) NOT NULL, 
    event_type VARCHAR(50) NOT NULL, 
    description TEXT, 
    starts_at DATETIME NOT NULL, 
    ends_at DATETIME NOT NULL, 
    location VARCHAR(255), 
    status VARCHAR(30) NOT NULL DEFAULT 'draft', 
    estimated_guests INTEGER, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(client_id) REFERENCES clients (id), 
    FOREIGN KEY(tenant_id) REFERENCES tenants (id)
);

CREATE INDEX ix_events_client_id ON events (client_id);

CREATE INDEX ix_events_tenant_id ON events (tenant_id);

CREATE INDEX ix_events_tenant_starts ON events (tenant_id, starts_at);

CREATE INDEX ix_events_tenant_status ON events (tenant_id, status);

UPDATE alembic_version SET version_num='3a5716a4896f' WHERE alembic_version.version_num = '07b0444c6490';

-- Running upgrade 3a5716a4896f -> 9a0948db920b

CREATE TABLE inventory_categories (
    id BIGINT NOT NULL AUTO_INCREMENT, 
    tenant_id BIGINT NOT NULL, 
    name VARCHAR(120) NOT NULL, 
    description VARCHAR(255), 
    is_active BOOL NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(tenant_id) REFERENCES tenants (id), 
    CONSTRAINT uq_inventory_category_tenant_id UNIQUE (tenant_id, id), 
    CONSTRAINT uq_inventory_category_tenant_name UNIQUE (tenant_id, name)
);

CREATE INDEX ix_inventory_categories_tenant_id ON inventory_categories (tenant_id);

CREATE TABLE inventory_items (
    id BIGINT NOT NULL AUTO_INCREMENT, 
    tenant_id BIGINT NOT NULL, 
    category_id BIGINT, 
    sku VARCHAR(60) NOT NULL, 
    name VARCHAR(180) NOT NULL, 
    description TEXT, 
    item_type VARCHAR(20) NOT NULL, 
    quantity_total INTEGER NOT NULL, 
    unit VARCHAR(30) NOT NULL, 
    replacement_cost NUMERIC(12, 2), 
    rental_price NUMERIC(12, 2), 
    is_active BOOL NOT NULL, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT ck_inventory_quantity_nonnegative CHECK (quantity_total >= 0), 
    CONSTRAINT fk_inventory_item_category_tenant FOREIGN KEY(tenant_id, category_id) REFERENCES inventory_categories (tenant_id, id), 
    FOREIGN KEY(tenant_id) REFERENCES tenants (id), 
    CONSTRAINT uq_inventory_item_tenant_id UNIQUE (tenant_id, id), 
    CONSTRAINT uq_inventory_item_tenant_sku UNIQUE (tenant_id, sku)
);

CREATE INDEX ix_inventory_items_tenant_id ON inventory_items (tenant_id);

UPDATE alembic_version SET version_num='9a0948db920b' WHERE alembic_version.version_num = '3a5716a4896f';

-- Running upgrade 9a0948db920b -> cca590abfbf9

CREATE TABLE inventory_reservations (
    id BIGINT NOT NULL AUTO_INCREMENT, 
    tenant_id BIGINT NOT NULL, 
    event_id BIGINT NOT NULL, 
    inventory_item_id BIGINT NOT NULL, 
    quantity INTEGER NOT NULL, 
    status VARCHAR(20) NOT NULL DEFAULT 'reserved', 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT ck_reservation_quantity_positive CHECK (quantity > 0), 
    FOREIGN KEY(event_id) REFERENCES events (id), 
    FOREIGN KEY(inventory_item_id) REFERENCES inventory_items (id), 
    FOREIGN KEY(tenant_id) REFERENCES tenants (id), 
    CONSTRAINT uq_reservation_event_item UNIQUE (tenant_id, event_id, inventory_item_id)
);

CREATE INDEX ix_inventory_reservations_event_id ON inventory_reservations (event_id);

CREATE INDEX ix_inventory_reservations_inventory_item_id ON inventory_reservations (inventory_item_id);

CREATE INDEX ix_inventory_reservations_tenant_id ON inventory_reservations (tenant_id);

CREATE INDEX ix_reservation_tenant_item_status ON inventory_reservations (tenant_id, inventory_item_id, status);

UPDATE alembic_version SET version_num='cca590abfbf9' WHERE alembic_version.version_num = '9a0948db920b';

-- Running upgrade cca590abfbf9 -> a6ed79c99fba

CREATE TABLE inventory_movements (
    id BIGINT NOT NULL AUTO_INCREMENT, 
    tenant_id BIGINT NOT NULL, 
    inventory_item_id BIGINT NOT NULL, 
    reservation_id BIGINT NOT NULL, 
    movement_type VARCHAR(20) NOT NULL, 
    quantity INTEGER NOT NULL, 
    notes TEXT, 
    created_by BIGINT NOT NULL, 
    created_at DATETIME NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT ck_movement_type CHECK (movement_type IN ('dispatch', 'return')), 
    CONSTRAINT ck_movement_positive_quantity CHECK (quantity > 0), 
    FOREIGN KEY(created_by) REFERENCES users (id), 
    CONSTRAINT fk_movement_item_tenant FOREIGN KEY(tenant_id, inventory_item_id) REFERENCES inventory_items (tenant_id, id), 
    CONSTRAINT fk_movement_reservation_tenant FOREIGN KEY(tenant_id, reservation_id) REFERENCES inventory_reservations (tenant_id, id), 
    FOREIGN KEY(tenant_id) REFERENCES tenants (id)
);

CREATE INDEX ix_inventory_movements_tenant_id ON inventory_movements (tenant_id);

CREATE INDEX ix_movements_reservation_type ON inventory_movements (reservation_id, movement_type);

ALTER TABLE inventory_reservations ADD CONSTRAINT uq_inventory_reservation_tenant_id UNIQUE (tenant_id, id);

UPDATE alembic_version SET version_num='a6ed79c99fba' WHERE alembic_version.version_num = 'cca590abfbf9';

-- Running upgrade a6ed79c99fba -> 6eb5e9e6f8fb

CREATE TABLE inventory_incidents (
    id BIGINT NOT NULL AUTO_INCREMENT, 
    tenant_id BIGINT NOT NULL, 
    reservation_id BIGINT NOT NULL, 
    inventory_item_id BIGINT NOT NULL, 
    incident_type VARCHAR(20) NOT NULL, 
    quantity INTEGER NOT NULL, 
    description TEXT NOT NULL, 
    status VARCHAR(20) NOT NULL, 
    unit_cost NUMERIC(12, 2), 
    total_cost NUMERIC(12, 2), 
    reported_by BIGINT NOT NULL, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT ck_incident_type CHECK (incident_type IN ('damaged', 'lost', 'missing')), 
    CONSTRAINT ck_incident_status CHECK (status IN ('reported', 'assessed', 'resolved', 'cancelled')), 
    CONSTRAINT ck_incident_positive_quantity CHECK (quantity > 0), 
    CONSTRAINT ck_incident_total_cost CHECK (total_cost IS NULL OR total_cost >= 0), 
    CONSTRAINT ck_incident_unit_cost CHECK (unit_cost IS NULL OR unit_cost >= 0), 
    FOREIGN KEY(reported_by) REFERENCES users (id), 
    CONSTRAINT fk_incident_item_tenant FOREIGN KEY(tenant_id, inventory_item_id) REFERENCES inventory_items (tenant_id, id), 
    CONSTRAINT fk_incident_reservation_tenant FOREIGN KEY(tenant_id, reservation_id) REFERENCES inventory_reservations (tenant_id, id), 
    FOREIGN KEY(tenant_id) REFERENCES tenants (id)
);

CREATE INDEX ix_incidents_tenant_status ON inventory_incidents (tenant_id, status);

CREATE INDEX ix_inventory_incidents_tenant_id ON inventory_incidents (tenant_id);

UPDATE alembic_version SET version_num='6eb5e9e6f8fb' WHERE alembic_version.version_num = 'a6ed79c99fba';

-- Running upgrade 6eb5e9e6f8fb -> f3dd57d05ff3

CREATE TABLE inventory_adjustments (
    id BIGINT NOT NULL AUTO_INCREMENT, 
    tenant_id BIGINT NOT NULL, 
    incident_id BIGINT NOT NULL, 
    inventory_item_id BIGINT NOT NULL, 
    adjustment_type VARCHAR(30) NOT NULL, 
    quantity INTEGER NOT NULL, 
    reason TEXT NOT NULL, 
    created_by BIGINT NOT NULL, 
    created_at DATETIME NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT ck_adjustment_type CHECK (adjustment_type IN ('loss', 'quarantine')), 
    CONSTRAINT ck_adjustment_positive_quantity CHECK (quantity > 0), 
    FOREIGN KEY(created_by) REFERENCES users (id), 
    CONSTRAINT fk_adjustment_incident_tenant FOREIGN KEY(tenant_id, incident_id) REFERENCES inventory_incidents (tenant_id, id), 
    CONSTRAINT fk_adjustment_item_tenant FOREIGN KEY(tenant_id, inventory_item_id) REFERENCES inventory_items (tenant_id, id), 
    FOREIGN KEY(tenant_id) REFERENCES tenants (id), 
    CONSTRAINT uq_adjustment_incident UNIQUE (tenant_id, incident_id)
);

CREATE TABLE inventory_incident_charges (
    id BIGINT NOT NULL AUTO_INCREMENT, 
    tenant_id BIGINT NOT NULL, 
    incident_id BIGINT NOT NULL, 
    event_id BIGINT NOT NULL, 
    amount NUMERIC(12, 2) NOT NULL, 
    currency VARCHAR(3) NOT NULL DEFAULT 'MXN', 
    status VARCHAR(20) NOT NULL DEFAULT 'pending', 
    description TEXT, 
    created_by BIGINT NOT NULL, 
    created_at DATETIME NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT ck_charge_status CHECK (status IN ('pending', 'approved', 'waived', 'paid')), 
    CONSTRAINT ck_charge_amount_nonnegative CHECK (amount >= 0), 
    FOREIGN KEY(created_by) REFERENCES users (id), 
    CONSTRAINT fk_charge_event_tenant FOREIGN KEY(tenant_id, event_id) REFERENCES events (tenant_id, id), 
    CONSTRAINT fk_charge_incident_tenant FOREIGN KEY(tenant_id, incident_id) REFERENCES inventory_incidents (tenant_id, id), 
    FOREIGN KEY(tenant_id) REFERENCES tenants (id), 
    CONSTRAINT uq_charge_incident UNIQUE (tenant_id, incident_id)
);

CREATE INDEX ix_incidents_tenant_reservation ON inventory_incidents (tenant_id, reservation_id);

ALTER TABLE inventory_incidents ADD CONSTRAINT uq_inventory_incident_tenant_id UNIQUE (tenant_id, id);

ALTER TABLE inventory_items ADD COLUMN quantity_unavailable INTEGER NOT NULL DEFAULT '0';

UPDATE alembic_version SET version_num='f3dd57d05ff3' WHERE alembic_version.version_num = '6eb5e9e6f8fb';

-- Running upgrade f3dd57d05ff3 -> 379533853b76

CREATE UNIQUE INDEX ix_incident_charges_tenant_id ON inventory_incident_charges (tenant_id, id);

ALTER TABLE inventory_incident_charges ADD COLUMN approved_by BIGINT;

ALTER TABLE inventory_incident_charges ADD CONSTRAINT fk_incident_charge_approved_by FOREIGN KEY(approved_by) REFERENCES users (id);

CREATE TABLE inventory_charge_audits (
    id BIGINT NOT NULL AUTO_INCREMENT, 
    tenant_id BIGINT NOT NULL, 
    charge_id BIGINT NOT NULL, 
    previous_status VARCHAR(20) NOT NULL, 
    new_status VARCHAR(20) NOT NULL, 
    notes TEXT, 
    changed_by BIGINT NOT NULL, 
    created_at DATETIME NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT fk_charge_audit_tenant_id FOREIGN KEY(tenant_id) REFERENCES tenants (id), 
    CONSTRAINT fk_charge_audit_changed_by FOREIGN KEY(changed_by) REFERENCES users (id), 
    CONSTRAINT fk_charge_audit_tenant FOREIGN KEY(tenant_id, charge_id) REFERENCES inventory_incident_charges (tenant_id, id)
);

CREATE INDEX ix_charge_audit_tenant_charge ON inventory_charge_audits (tenant_id, charge_id);

UPDATE alembic_version SET version_num='379533853b76' WHERE alembic_version.version_num = 'f3dd57d05ff3';

-- Running upgrade 379533853b76 -> fc94a932cabb

