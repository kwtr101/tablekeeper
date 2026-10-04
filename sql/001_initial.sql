CREATE EXTENSION IF NOT EXISTS btree_gist;

CREATE TABLE api_keys (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    token_hash CHAR(64) NOT NULL UNIQUE,
    role TEXT NOT NULL CHECK (role IN ('admin', 'customer')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at TIMESTAMPTZ
);

CREATE TABLE restaurants (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name TEXT NOT NULL CHECK (length(trim(name)) > 0),
    timezone TEXT NOT NULL CHECK (length(timezone) > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE restaurant_tables (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    restaurant_id BIGINT NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
    name TEXT NOT NULL CHECK (length(trim(name)) > 0),
    capacity INTEGER NOT NULL CHECK (capacity > 0),
    active BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE (restaurant_id, name),
    UNIQUE (id, restaurant_id)
);

CREATE TABLE reservations (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    restaurant_id BIGINT NOT NULL REFERENCES restaurants(id),
    table_id BIGINT NOT NULL,
    customer_key_id BIGINT REFERENCES api_keys(id),
    party_size INTEGER NOT NULL CHECK (party_size > 0),
    starts_at TIMESTAMPTZ NOT NULL,
    ends_at TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL DEFAULT 'confirmed' CHECK (status IN ('confirmed', 'cancelled')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (starts_at < ends_at),
    FOREIGN KEY (table_id, restaurant_id) REFERENCES restaurant_tables(id, restaurant_id),
    CONSTRAINT reservations_no_table_overlap
        EXCLUDE USING gist (
            table_id WITH =,
            tstzrange(starts_at, ends_at, '[)') WITH &&
        ) WHERE (status = 'confirmed')
);

CREATE INDEX reservations_customer_start_idx ON reservations (customer_key_id, starts_at);
CREATE INDEX reservations_restaurant_start_idx ON reservations (restaurant_id, starts_at);
