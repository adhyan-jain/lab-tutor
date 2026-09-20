import { redirect } from "next/navigation";

/** /settings has no content of its own: it opens the Classroom section,
 * keeping the selected classroom if the link carried one. */
export default async function SettingsIndex({
  searchParams,
}: {
  searchParams: Promise<{ classroom?: string }>;
}) {
  const { classroom } = await searchParams;
  redirect(`/settings/classroom${classroom ? `?classroom=${encodeURIComponent(classroom)}` : ""}`);
}
