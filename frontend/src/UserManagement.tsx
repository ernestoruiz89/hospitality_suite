import { AccessManager } from "./AccessManager"
import type { Property } from "./api"

export function UserManagement({ property, section }: { property: Property; section: "directory" | "assign" }) {
  return <div className="space-y-6">
    <div>
      <h1 className="text-3xl font-semibold">{section === "directory" ? "Directorio de usuarios" : "Conceder acceso"}</h1>
      <p className="mt-1 text-sm text-muted-foreground">{section === "directory"
        ? `Personal con acceso a ${property.brand_name || property.property_name}.`
        : `Asigne un usuario y sus roles a ${property.brand_name || property.property_name}.`}</p>
    </div>
    <AccessManager property={property} section={section} />
  </div>
}
