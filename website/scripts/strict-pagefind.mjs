// Pagefind 1.5.2 swallows index-load errors. This narrow build compatibility
// patch lets the existing UI show retry instead of displaying partial results.
// Refuse a changed upstream bundle so upgrades require a fresh review.
export const strictChunkMarker = 'ralf-strict-chunks-v1';
export function strictPagefindChunks(source) {
  const swallowed = 'catch(e){console.error(`Failed to load the index chunk ${url}:\n${e?.toString()}`);}';
  if (source.split(swallowed).length !== 2)
    throw new Error('Pagefind index loader changed; review strict chunk failure handling before building.');
  return source.replace(swallowed, `catch(e){/* ${strictChunkMarker} */throw e;}`);
}
