BEGIN;

ALTER TABLE "MaintenanceLog"
    ADD COLUMN IF NOT EXISTS "room_id" INTEGER;

DO $$
BEGIN
    ALTER TABLE "MaintenanceLog"
        ADD CONSTRAINT "MaintenanceLog_room_id_fkey"
        FOREIGN KEY ("room_id")
        REFERENCES "Rooms" ("id")
        ON DELETE SET NULL;
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

CREATE INDEX IF NOT EXISTS idx_maintenance_room_id
    ON "MaintenanceLog" ("room_id");

COMMIT;
