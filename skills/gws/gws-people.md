---
name: gws-people
description: "Google People: Manage contacts, contact groups, and directory profiles."
---

# people (v1)

```bash
gws people <resource> <method> [flags]
```

## API Resources

### people

  - `batchCreateContacts` — Create a batch of new contacts.
  - `batchDeleteContacts` — Delete a batch of contacts.
  - `batchUpdateContacts` — Update a batch of contacts.
  - `createContact` — Create a new contact.
  - `deleteContact` — Delete a contact person.
  - `deleteContactPhoto` — Delete a contact's photo.
  - `get` — Get information about a person by resource name. Use `people/me` for the authenticated user. Requires `personFields` param.
  - `getBatchGet` — Get information about a list of specific people by resource name.
  - `listDirectoryPeople` — List domain profiles and contacts in the user's domain directory.
  - `searchContacts` — Search contacts by query string.
  - `searchDirectoryPeople` — Search domain profiles and contacts in the directory.
  - `updateContact` — Update contact data for an existing contact.
  - `updateContactPhoto` — Update a contact's photo.
  - `connections` — List the authenticated user's contacts (sub-resource: `list`)

### contactGroups

  - `batchGet` — Get a list of contact groups by resource name.
  - `create` — Create a new contact group.
  - `delete` — Delete an existing contact group.
  - `get` — Get a specific contact group.
  - `list` — List all contact groups owned by the authenticated user.
  - `update` — Update the name of an existing contact group.
  - `members` — Modify members of a contact group (sub-resource)

### otherContacts

  - `copyOtherContactToMyContactsGroup` — Copy an "Other contact" into the user's "myContacts" group.
  - `list` — List all "Other contacts" (auto-created from interactions).
  - `search` — Search "Other contacts" by query string.

## Key Parameters

- `personFields` (required for `get`/`getBatchGet`): comma-separated fields to return, e.g. `names,emailAddresses,phoneNumbers,photos,organizations`
- `resourceName`: e.g. `people/me`, `people/c12345`

## Discovering Commands

```bash
gws people --help
gws people people --help
gws schema people.people.get
```

Use `gws schema` output to build your `--params` and `--json` flags.
