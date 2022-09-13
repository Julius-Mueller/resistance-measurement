# resistance-measurement

This project comprises a suite of python scripts that enable automated
temperature dependent resistance measurement runs using Keithly source and
nanovolt meters as well as a variety of cryo-cooling hardware, all contained in
an easy-to-use graphical user interface.

For details on how to use the software, as well as how to work with and expand
the individual modules, a brief handbook is provided.

CryoConnector_ver3500.msi is provided by Oxford Cryosystems Ltd.

# Installation instructions

In order to use VISA on the GPIB protocol, the appropriate drivers need to be
installed, namely ni-visa and ni-488.2, see
https://www.ni.com/de-de/support/downloads/drivers.html

The cryoconnector application is a requirement for using Oxford coolers, the
user will be prompted to install it from the .msi file above if it is not
installed already.
