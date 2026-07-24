import { redirect } from "next/navigation";

export default function Home() {
  // Middleware sends signed-out users to /login before this runs.
  redirect("/chat");
}
