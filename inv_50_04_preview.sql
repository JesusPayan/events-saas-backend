-- Running upgrade 8a137f1a4c24 -> b7e504000001

ALTER TABLE logistics_orders ADD COLUMN dispatched_at DATETIME;

ALTER TABLE logistics_orders ADD COLUMN dispatched_by BIGINT;

ALTER TABLE logistics_orders ADD COLUMN dispatch_notes TEXT;

ALTER TABLE logistics_orders ADD COLUMN delivered_at DATETIME;

ALTER TABLE logistics_orders ADD COLUMN delivered_by BIGINT;

ALTER TABLE logistics_orders ADD COLUMN delivery_notes TEXT;

ALTER TABLE logistics_orders ADD CONSTRAINT fk_logistics_orders_dispatched_by FOREIGN KEY(dispatched_by) REFERENCES users (id);

ALTER TABLE logistics_orders ADD CONSTRAINT fk_logistics_orders_delivered_by FOREIGN KEY(delivered_by) REFERENCES users (id);

ALTER TABLE logistics_orders DROP CHECK ck_logistics_orders_status;

ALTER TABLE logistics_orders ADD CONSTRAINT ck_logistics_orders_status CHECK (status IN ('pending', 'in_progress', 'prepared', 'dispatched', 'delivered', 'cancelled'));

CREATE TABLE logistics_order_status_history (
    id BIGINT NOT NULL AUTO_INCREMENT, 
    tenant_id BIGINT NOT NULL, 
    logistics_order_id BIGINT NOT NULL, 
    previous_status VARCHAR(20), 
    new_status VARCHAR(20) NOT NULL, 
    changed_by BIGINT NOT NULL, 
    notes TEXT, 
    created_at DATETIME NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT fk_logistics_history_order FOREIGN KEY(tenant_id, logistics_order_id) REFERENCES logistics_orders (tenant_id, id), 
    CONSTRAINT fk_logistics_history_user FOREIGN KEY(changed_by) REFERENCES users (id)
);

CREATE INDEX ix_logistics_history_tenant_order ON logistics_order_status_history (tenant_id, logistics_order_id);

UPDATE alembic_version SET version_num='b7e504000001' WHERE alembic_version.version_num = '8a137f1a4c24';

