import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AppProviders } from "@/app/providers";
import { createBackendGateway } from "@/lib/api/fetch-client";
import { __resetAuthStandIn } from "@/mocks/handlers";
import { UserSearch } from "./user-search";

const BASE_URL = "http://localhost:8000";
const push = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));

beforeEach(() => {
  push.mockClear();
  sessionStorage.clear();
  __resetAuthStandIn();
});

async function loginAsAlice() {
  await createBackendGateway(BASE_URL).login({
    email: "alice@example.com",
    password: "password123",
  });
}

describe("UserSearch", () => {
  it("searches users and navigates to the selected profile", async () => {
    await loginAsAlice();
    render(
      <AppProviders>
        <UserSearch />
      </AppProviders>,
    );

    const input = screen.getByLabelText(/search users/i);
    fireEvent.change(input, { target: { value: "bo" } });
    fireEvent.submit(input.closest("form")!);

    expect(await screen.findByRole("option", { name: /bob/i })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("option", { name: /bob/i }));

    expect(push).toHaveBeenCalledWith("/profile/bob");
  });

  it("shows an empty-state message when nothing matches", async () => {
    await loginAsAlice();
    render(
      <AppProviders>
        <UserSearch />
      </AppProviders>,
    );

    const input = screen.getByLabelText(/search users/i);
    fireEvent.change(input, { target: { value: "nobody-here" } });
    fireEvent.submit(input.closest("form")!);

    expect(await screen.findByText(/no users found/i)).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
  });
});
