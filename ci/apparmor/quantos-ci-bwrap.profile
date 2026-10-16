# CANDIDATE ONLY: host-policy installation requires separate explicit authorization.
# Application-level userns exception; executable descendants may inherit this label.
# This does not replace bwrap's cap-drop, mount, namespace or seccomp boundaries.
abi <abi/4.0>,

profile quantos_ci_bwrap /usr/bin/bwrap flags=(unconfined) {
  userns,
}
