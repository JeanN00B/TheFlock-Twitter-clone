import { RegisterForm } from "@/features/auth/register-form";

/** Thin inbound adapter: layout owns providers, this page owns placement. */
export default function RegisterPage() {
  return (
    <main className="flex min-h-svh flex-col items-center justify-center bg-muted p-6 md:p-10">
      <div className="w-full max-w-sm md:max-w-4xl">
        <RegisterForm />
      </div>
    </main>
  );
}
