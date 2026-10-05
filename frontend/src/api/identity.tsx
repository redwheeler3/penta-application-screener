import { createContext, type ReactNode, useContext, useMemo } from "react";

import { type ApiClient, identityClient, type RequestIdentity } from "./client";

const RequestClient = createContext<ApiClient | null>(null);

export function RequestIdentityProvider({ identity, children }: { identity: RequestIdentity; children: ReactNode }) {
  const { kind, id } = identity;
  const client = useMemo(() => identityClient({ kind, id }), [kind, id]);
  return <RequestClient value={client}>{children}</RequestClient>;
}

/** APIs below the authenticated workspace retain its captured request client.
 * Public components and manual harnesses can use their unbound module exports. */
export function useCommitteeApi<T>(module: T & { createApi: (client: ApiClient) => T }): T {
  const client = useContext(RequestClient);
  return useMemo(() => client ? module.createApi(client) : module, [client, module]);
}
