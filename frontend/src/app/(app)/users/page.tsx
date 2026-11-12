"use client";

import { ResourcePage } from "@/components/ResourcePage";
import { Alert, Badge } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { labelOf, ROLES } from "@/lib/types";

export default function UsersPage() {
  const { isAdmin } = useAuth();
  if (!isAdmin) return <Alert kind="warning">Only school administrators can manage user accounts.</Alert>;

  return (
    <ResourcePage
      title="Users"
      description="Accounts that can sign in. Admins manage everything, schedulers edit school data and schedules, teachers can only view."
      endpoint="/api/users"
      adminOnly
      lookups={{ teachers: "/api/teachers" }}
      columns={[
        { header: "Name", cell: (row) => <span className="font-medium">{row.full_name}</span> },
        { header: "Email", cell: (row) => row.email },
        { header: "Role", cell: (row) => labelOf(ROLES, row.role) },
        {
          header: "Status",
          cell: (row) => (row.is_active ? <Badge tone="emerald">active</Badge> : <Badge>deactivated</Badge>),
        },
      ]}
      fields={[
        { name: "full_name", label: "Full name", type: "text", required: true },
        { name: "email", label: "Email", type: "email", required: true, createOnly: true },
        { name: "role", label: "Role", type: "select", required: true, options: () => ROLES },
        {
          name: "password",
          label: "Password",
          type: "password",
          hint: "At least 10 characters. When editing, leave blank to keep the current password.",
        },
        {
          name: "teacher_id",
          label: "Linked teacher record",
          type: "select",
          nullable: true,
          hint: "Optional. Links a teacher account to their teacher record.",
          options: (l) => (l.teachers ?? []).map((t) => ({ value: t.id, label: `${t.full_name} (${t.employee_id})` })),
        },
        { name: "is_active", label: "Account is active", type: "checkbox" },
      ]}
      defaults={{ full_name: "", email: "", role: "scheduler", password: "", teacher_id: "", is_active: true }}
      toPayload={(values, editing) => {
        const body = { ...values };
        if (editing && !body.password) delete body.password;
        if (!editing) delete body.is_active;
        return body;
      }}
      searchText={(row) => `${row.full_name} ${row.email} ${row.role}`}
    />
  );
}
