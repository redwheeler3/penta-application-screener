import { createContext, type ReactNode, useContext, useMemo } from "react";

import { type ApiClient, identityClient, type RequestIdentity } from "./client";

const RequestClient = createContext<ApiClient | null>(null);

export function RequestIdentityProvider({ identity, children }: { identity: RequestIdentity; children: ReactNode }) {
  const { kind, id } = identity;
  const client = useMemo(() => identityClient({ kind, id }), [kind, id]);
  return <RequestClient value={client}>{children}</RequestClient>;
}

/** Protected APIs require the authenticated workspace's captured request client. */
export function useCommitteeApi<T>(module: { createApi: (client: ApiClient) => T }): T {
  const client = useContext(RequestClient);
  if (client === null) throw new Error("Protected API requires RequestIdentityProvider.");
  return useMemo(() => module.createApi(client), [client, module]);
}
