""" Connect to KEITHLEY SourceMeter and NanovoltMeter, start resistance
	measurement in Delta-mode and write data to file.
"""

import os
import time
import Tkinter as tk
import ttk
import tkFileDialog, tkMessageBox
import getpass
from threading import Thread

import csv
import numpy as np
import matplotlib.pyplot as plt
# plt.switch_backend('GTKAgg')
from matplotlib.widgets import Button, TextBox

import pyvisa as visa
from Cryostat import Cryostat


class ResistanceMeasurement:

	def __init__(self, SourceMeterPort=24, VoltMeterPort=7, testMode=0):
		""" Initiates the KEITHLEY devices.
		:param SourceMeterPort: GPIB-Portnumber of the Sourcemeter
		:param VoltMeterPort: GPIB-Portnumber of the Nanovoltmeter
		:param testMode: In ~ GUI works without connected hardware
		"""
		self.testMode = testMode
		self.cwd = os.path.join('C:/Users', getpass.getuser(),
								'ResistanceMeasurement')
		if not os.path.exists(self.cwd):
			os.mkdir(self.cwd)

		self.CCcwd = os.path.join('C:\Users', getpass.getuser(), 'AppData',
								  'Roaming', 'CryoConnector', '')

		self.SPort = SourceMeterPort
		self.VPort = VoltMeterPort
		self.I_Range_init = 1e-6
		self.I_Range = self.I_Range_init    # Sourcemeter current range
		self.I_min = 50e-12					# Min sourcemeter current
		self.I_max = 1e-3					# Max safe current
		self.I_compliance = 1e-3			# Compliance current limit
		self.I = self.I_min					# Current setpoint in A
		self.U_min = 5e-6					# Min sourcemeter voltage
		self.U_max = 21.0					# Max safe voltage
		self.U_compliance = 5.9				# Compliance voltage limit
		self.U = self.U_min					# Voltage setpoint in V
		self.T_sample = 300.0				# T @ sample, initially RT
		self.T_cryo = 300.0					# T @ cryostat, initially RT
		self.limit = 5.0					# Limit for R-spread in %
		self.stageList = []					# List of stages in meas.run
		self.XRDlist = ('None',)			# List of XRD sweep names
		self.latestDataPoint = np.array([])	# Latest measurement data

		self.stopFlag = 0					# All activity stop flag
		self.stopContinuousFlag = 0			# Cont. R-meas. stop flag

		self.stopButtonActive = 0			# Stop btn. operational y/n
		self.continuousActive = 0			# Cont. R-meas. active y/n
		self.calibrateActive = 0			# I-calibration active y/n

		self.fig, self.ax = plt.subplots()  # Initiate GUI root window
		self.scatterplot = self.ax.scatter([], [], c='blue')
		self.dataShowing = ''				# For updatePlot function...
		self.dataToSave = 'measurementData'	# For saveFile function ...
		self.delimiter = ','				# Delimiter for save files

		self.rm = visa.ResourceManager()

		self.use_keit = 0					# Use KEITHLEY hardware y/n
		self.use_cryo = 0					# Use cryostat hardware y/n
		self.use_apex = 0					# Use Bruker APEX PC y/n

		self.start()

	# start function to initialise the measurement environment - - - - -

	def _addCryostatButton(self):
		""" Callback function for the Cryostat button in self.start.
		Initialises cryostat.
		"""
		self.cryostat = Cryostat(CCWorkingFolder=self.CCcwd,
								 testMode=self.testMode)
		if self.cryostat.index != -1:
			self.text1.set(self.cryostat.deviceName)
			self.use_cryo = 1

	def connectK2401(self, port):
		""" Attempts to initialise the Keithely K2401 Sourcemeter at the
		provided port.
		"""
		self.K2401 = self.rm.open_resource("GPIB0::{:.0f}::INSTR".format(port))
		self.K2401.read_termination = '\n'
		self.K2401.write_termination = '\n'

		# reset GPIB
		self.K2401.write("*RST")
		# select terminals
		self.K2401.write(":ROUT:TERM REAR")
		# no remote sensing with K2401
		self.K2401.write(":SYST:RSEN OFF")
		# enable auto-zero
		self.K2401.write(":SYST:AZER ON")
		# set to supply current
		self.K2401.write(":SOUR:FUNC CURR")
		# fixed current mode
		self.K2401.write(":SOUR:CURR:MODE FIX")
		# source range
		self.K2401.write(":SOUR:CURR:RANG {:.2e}".format(self.I_Range))
		# source amplitude
		self.K2401.write(":SOUR:CURR:LEV {:.2e}".format(self.I))
		# set compliance limits
		self.K2401.write(":SENS:CURR:PROT:LEV {:.2e}".format(self.I_compliance))
		self.K2401.write(":SENS:VOLT:PROT:LEV {:.2e}".format(self.U_compliance))
		# enable concurrent measurements
		self.K2401.write(":SENS:FUNC:CONC ON")
		# enable all functions
		self.K2401.write(":SENS:FUNC:ON 'VOLT', 'CURR'")
		# specify data elements to return in data string
		self.K2401.write(":FORM:ELEM VOLT, CURR")

	def connectK2182(self, port):
		""" Attempts to initialise the Keithely K2182 Voltmeter at the
		provided port.
		"""
		self.K2182 = self.rm.open_resource("GPIB0::{:.0f}::INSTR".format(port))
		self.K2182.read_termination = '\n'
		self.K2182.write_termination = '\n'

		# reset GPIB
		self.K2182.write("*RST")
		# select voltage
		self.K2182.write(":SENS:FUNC 'VOLT'")
		# select channel 1
		self.K2182.write(":SENS:CHAN 1")
		# auto range on
		self.K2182.write(":SENS:VOLT:CHAN1:RANG:AUTO ON")

	def _testK2401(self):
		""" Tests whether the K2401 is connected to the selected port.
		"""
		try:
			port = int(self.SPortVar.get())
			self.connectK2401(port)
			self.K2401.write("*IDN?")
			IDN = self.K2401.read()
		except:
			IDN = ''
		if ('KEITHLEY' in IDN) and ('2401' in IDN):
			self.use_K2401 = 1
			self.testVar2401.set('ready')
			print 'Connected to: ', IDN
		elif self.testMode:
			self.use_K2401 = 1
			self.testVar2401.set('testMode')
		else:
			self.use_K2401 = 0
			self.testVar2401.set('not found')

	def _testK2182(self):
		""" Tests whether the K2182 is connected to the selected port.
		"""
		try:
			port = int(self.VPortVar.get())
			self.connectK2182(port)
			self.K2182.write("*IDN?")
			IDN = self.K2182.read()
		except:
			IDN = ''
		if ('KEITHLEY' in IDN) and ('2182' in IDN):
			self.use_K2182 = 1
			self.testVar2182.set('ready')
			print 'Connected to: ', IDN
		elif self.testMode:
			self.use_K2182 = 1
			self.testVar2182.set('testMode')
		else:
			self.use_K2182 = 0
			self.testVar2182.set('not found')

	def _keithleyOkButton(self):
		""" Callback function for the OK button.
		"""
		self.use_keit = (self.use_K2401 and self.use_K2182)
		if self.use_keit:
			self.text0.set('K2401 & K2182')
		self.keithleyWindow.destroy()

	def _addKeithleysButton(self):
		""" Callback function for the Keithley Sourcemeter/Voltmeter
		button in self.start. Initialises K2401, K2821.
		"""
		# Keithley device addresses range from 0-30
		ports = range(31)

		self.keithleyWindow = tk.Toplevel()
		self.keithleyWindow.title('Connect to KEITHLEY hardware')

		sms = tk.Label(self.keithleyWindow, text='Please select the appropriate Ports:')
		sms.grid(row=0, column=0, rowspan=2, columnspan=4, padx=30, pady=30)

		sm0 = tk.Label(self.keithleyWindow, text='K2401 Sourcemeter')
		sm0.grid(row=2, column=0, padx=20, sticky='E')

		self.SPortVar = tk.StringVar()
		self.SPortVar.set(self.SPort)
		om0 = tk.OptionMenu(self.keithleyWindow, self.SPortVar, *ports)
		om0.grid(row=2, column=1, sticky='E')

		sb0 = tk.Button(self.keithleyWindow, text='test', command=self._testK2401)
		sb0.grid(row=2, column=2, sticky='W')

		self.testVar2401 = tk.StringVar()
		self._testK2401()
		sm01 = tk.Label(self.keithleyWindow, textvariable=self.testVar2401)
		sm01.grid(row=2, column=3, padx=20, sticky='E')

		sm1 = tk.Label(self.keithleyWindow, text='K2182 Voltmeter')
		sm1.grid(row=3, column=0, padx=20, sticky='E')

		self.VPortVar = tk.StringVar()
		self.VPortVar.set(self.VPort)
		om1 = tk.OptionMenu(self.keithleyWindow, self.VPortVar, *ports)
		om1.grid(row=3, column=1, sticky='E')

		sb1 = tk.Button(self.keithleyWindow, text='test', command=self._testK2182)
		sb1.grid(row=3, column=2, sticky='W')

		self.testVar2182 = tk.StringVar()
		self._testK2182()
		sm11 = tk.Label(self.keithleyWindow, textvariable=self.testVar2182)
		sm11.grid(row=3, column=3, padx=20, sticky='E')

		sb2 = tk.Button(self.keithleyWindow, text='OK', command=self._keithleyOkButton)
		sb2.grid(row=4, column=3, padx=20, pady=20)

		self.keithleyWindow.wait_window()

	def _startOkButton(self):
		""" Callback function for the OK-button in self.start. Decides
		which measurement run to initialise based on the selected
		hardware and closes the startWindow.
		"""
		if (self.use_keit, self.use_cryo, self.use_apex) == (0, 0, 0):
			self.startWindow.destroy()

		elif (self.use_keit, self.use_cryo, self.use_apex) == (1, 0, 0):
			self.startWindow.destroy()
			self.temperatureRun()

		elif (self.use_keit, self.use_cryo, self.use_apex) == (1, 1, 0):
			self.startWindow.destroy()
			self.temperatureAutoRun()

		else:
			self.startWindow.destroy()

	def start(self):
		""" Asks the user which hardware to connect to and starts the
		measurement GUI.
		"""
		self.startWindow = tk.Toplevel()
		self.startWindow.title('Configure hardware')

		sm0 = tk.Label(self.startWindow, text='Please choose which hardware to connect to:')
		sm0.grid(row=0, column=0, rowspan=2, columnspan=2, padx=30, pady=30)

		sb0 = tk.Button(self.startWindow, text='Source- & Voltmeter', command=self._addKeithleysButton)
		sb0.grid(row=2, column=0, padx=20, sticky='EW')

		self.text0 = tk.StringVar()
		self.text0.set('no device selected')
		sl0 = tk.Label(self.startWindow, textvariable=self.text0, font='Helvetica 9 italic')
		sl0.grid(row=2, column=1, sticky='W')

		sb1 = tk.Button(self.startWindow, text='Cryostat', command=self._addCryostatButton)
		sb1.grid(row=3, column=0, padx=20, sticky='EW')

		self.text1 = tk.StringVar()
		self.text1.set('no device selected')
		sl1 = tk.Label(self.startWindow, textvariable=self.text1, font='Helvetica 9 italic')
		sl1.grid(row=3, column=1, sticky='W')

		sb2 = tk.Button(self.startWindow, text='Bruker APEX PC')
		sb2.grid(row=4, column=0, padx=20, sticky='EW')

		self.text2 = tk.StringVar()
		self.text2.set('no device selected')
		sl2 = tk.Label(self.startWindow, textvariable=self.text2, font='Helvetica 9 italic')
		sl2.grid(row=4, column=1, sticky='W')

		sb3 = tk.Button(self.startWindow, text='OK', command=self._startOkButton)
		sb3.grid(column=1, padx=20, pady=20, sticky='E')

		self.startWindow.wait_window()

	# hardware functions to perform calibration and measurements - - - -

	def voltage(self, n=1, deltaMode=1):
		""" Measures voltage directly or via delta-mode. Returns n values
		as array.
		"""
		# Check if OUTPut is already on. Device beeps when OUTPut is
		# turned ON, this is to avoid turning it ON and OFF repeatedly.
		self.K2401.write(":OUTP?")
		outputOnInitially = int(self.K2401.read())

		U = np.zeros(n)
		U_neg = np.ones(n)
		self.K2401.write(":SOUR:CURR:RANG {:.2e}".format(self.I))
		self.K2401.write(":SOUR:CURR:LEV {:.2e}".format(self.I))

		if not outputOnInitially:
			self.K2401.write(":OUTP ON")

		for i in range(n):
			self.K2182.write(":READ?")
			U[i] = float(self.K2182.read())
			if deltaMode == 1:
				# switch current and calculate average
				self.K2401.write(":SOUR:CURR:LEV {:.2e}".format(-self.I))
				self.K2182.write(":READ?")
				U_neg[i] = float(self.K2182.read())
				self.K2401.write(":SOUR:CURR:LEV {:.2e}".format(self.I))

		if not outputOnInitially:
			self.K2401.write(":OUTP OFF")

		if deltaMode == 1:
			U = 0.5*(U - U_neg)
		if n == 1:
			U = U[0]
		return U

	def sense_UIR(self):
		"""
		Measures voltage, current and resistance at the power supply.
		:return: U, I, R
		"""
		U = I = R = 0.0
		self.K2401.write(":OUTP?")
		outputOnInitially = int(self.K2401.read())

		if outputOnInitially:
			self.K2401.write(":READ?")
			datastring = self.K2401.read()
			stringarray = datastring.split(',')
			U = float(stringarray[0])
			I = float(stringarray[1])
			self.latest_I = I
			R = U/I
		return U, I, R

	def resistance(self, n=1, deltaMode=1):
		"""
		Four-point resistance measurement using voltage() and sense_UIR().
		Returns n values as array, or float if n==1.
		"""
		# Check if OUTPut is already on. Device beeps when OUTPut is
		# turned ON, this is to avoid turning it ON and OFF repeatedly.
		self.K2401.write(":OUTP?")
		outputOnInitially = int(self.K2401.read())

		U = np.zeros(n)
		I = np.zeros(n)
		U_neg = np.ones(n)
		I_neg = np.zeros(n)
		self.K2401.write(":SOUR:CURR:LEV {:.2e}".format(self.I))

		if not outputOnInitially:
			self.K2401.write(":OUTP ON")

		for i in range(n):
			self.K2182.write(":READ?")
			U[i] = float(self.K2182.read())
			_, I[i], _ = self.sense_UIR()
			if deltaMode == 1:
				# switch current and calculate average
				self.K2401.write(":SOUR:CURR:LEV {:.2e}".format(-self.I))
				self.K2182.write(":READ?")
				U_neg[i] = float(self.K2182.read())
				_, I_neg[i], _ = self.sense_UIR()
				self.K2401.write(":SOUR:CURR:LEV {:.2e}".format(self.I))

		if not outputOnInitially:
			self.K2401.write(":OUTP OFF")

		R = U/I
		if deltaMode == 1:
			R_neg = U_neg/I_neg
			R = 0.5*(R - R_neg)
		if n == 1:
			R = R[0]
		return R

	def calibrate(self, n=10, step=10, wait=0.0, plot=0):
		""" Ramps up the current until spread of measured resistances
		(std) is smaller than the self.limit in %.

		:param n: The number of measurements per current setting
		:param step: The multiplicative increase of the current
		setpoint until desired precision is reached
		:param wait: Time in s to wait between measurements of R
		:param plot: Boolean to determine whether to self.updatePlot
		"""
		self.dataToSave = 'calibrationData'

		rel_max = self.limit*0.01
		self.I = self.I_min
		slow = 0
		t0 = time.time()
		Rarrayplus = np.zeros(n)
		Rarrayminus = np.zeros(n)

		self.CaliHead = np.array([["T_sample", "T_cryo", "I", "U", "R", "t"],
								  ["K", "K", "A", "V", "Ohms", "s"]])

		self.K2401.write(":OUTP ON")

		path = os.path.join(self.cwd, 'cali.out')
		with open(path, 'w') as file:
			for line in self.CaliHead:
				string = self.delimiter.join(str(x) for x in line)
				file.write(string + '\n')
		while self.stopFlag == 0:
			if (abs(self.I) > self.I_max) and (slow == 0):
				slow = 1
				if step > 5.0:
					self.I = self.I/step
					step = step/5.0
					self.I = step * self.I
				else:
					self.I = self.I_max
			if (abs(self.I) > self.I_max) and (slow == 1):
				self.I = self.I_min
				self.I_Range = self.I_Range_init
				print "Calibration failed: Reached current threshold before " \
					  "measurement spread within limits!"
				print "Current setpoint returned to {} A.\n".format(self.I)
				break
			print "Calibrating... I = {} A".format(self.I)
			self.t2.set_val(self.I)

			# n times resistance with self.I in one direction (plus)
			for i in range(n):
				if self.stopFlag:
					break

				if not ((abs(self.I) == self.I_min) and (i == 0)):
					time.sleep(wait)

				if self.use_cryo:
					self.cryostat.updateStatus()
					self.T_cryo = self.cryostat.cryoTemp
					self.T_sample = self.cryostat.sampleTemp

				t = time.time() - t0
				U = self.voltage(n=1, deltaMode=0)
				_, I, _ = self.sense_UIR()
				R = U/I
				Rarrayplus[i] = R

				data = np.array([self.T_sample, self.T_cryo, I, U, R, t])
				self.latestDataPoint = data

				data_string = self.delimiter.join(str(x) for x in data)
				with open(path, 'a') as file:
					file.write(data_string + '\n')

				if plot:
					self._temperatureRun_updatePlot(function='calibrate')
					# Avoid Matplotlib window crashing:
					#plt.pause(0.05)
					# actually makes Matplotlib window crash when running function in Thread

			# n times resistance with self.I in other direction (minus)
			self.I = -self.I
			for i in range(n):
				if self.stopFlag:
					break

				if not ((abs(self.I) == self.I_min) and (i == 0)):
					time.sleep(wait)

				if self.use_cryo:
					self.cryostat.updateStatus()
					self.T_cryo = self.cryostat.cryoTemp
					self.T_sample = self.cryostat.sampleTemp

				t = time.time() - t0
				U = self.voltage(n=1, deltaMode=0)
				_, I, _ = self.sense_UIR()
				R = U / I
				Rarrayminus[i] = R

				data = np.array([self.T_sample, self.T_cryo, I, U, R, t])
				self.latestDataPoint = data

				data_string = self.delimiter.join(str(x) for x in data)
				with open(path, 'a') as file:
					file.write(data_string + '\n')

				if plot:
					self._temperatureRun_updatePlot(function='calibrate')
					# Avoid Matplotlib window crashing:
					#plt.pause(0.05)
					# actually makes Matplotlib window crash when running function in Thread
			self.I = -self.I

			avgplus = Rarrayplus.sum()/n
			avgminus = Rarrayminus.sum()/n
			stdplus = Rarrayplus.std()
			stdminus = Rarrayminus.std()
			avg = (avgplus + avgminus)/2
			std = (stdplus + stdminus)/2
			rel = abs(std/avg)
			print "Spread = {} %\n".format(rel*100)
			if rel < rel_max:
				print "Calibration successful: Current setpoint set to " \
					  "{} A.\n".format(self.I)
				break
			self.I = step * self.I
			self.I_Range = self.I

		self.K2401.write(":OUTP OFF")
		self.calibrateActive = 0
		self.b0.color = 'lightgray'
		self.b0.hovercolor = 'lightskyblue'
		self.b0.label.set_text('Calibrate I')

	def IVcurve(self, n=10, step=10, wait=0.0, plot=0):
		""" Ramps up the voltage and maps current.

		:param n: The number of measurements per voltage setting
		:param step: The multiplicative increase of the voltage
		setpoint
		:param wait: Time in s to wait between measurements of I
		:param plot: Boolean to determine whether to self.updatePlot
		"""
		self.dataToSave = 'IVcurveData'
		reachedEnd = 0
		self.U = self.U_min

		t0 = time.time()

		self.IVcurveHead = np.array([["T_sample", "T_cryo", "U_source", "I_sense", "R_calc", "U_sample", "t"],
								  ["K", "K", "V", "A", "Ohms", "V", "s"]])

		# set to supply voltage
		self.K2401.write(":SOUR:FUNC VOLT")
		self.K2401.write(":SOUR:VOLT:LEV {:.2e}".format(self.U))
		self.K2401.write(":OUTP ON")

		path = os.path.join(self.cwd, 'IVcurve.out')
		with open(path, 'w') as file:
			for line in self.IVcurveHead:
				string = self.delimiter.join(str(x) for x in line)
				file.write(string + '\n')
		while self.stopFlag == 0:
			if (abs(self.U) >= self.U_max):
				if reachedEnd:
					self.U = self.U_min
					break
				else:
					self.U = self.U_max
					reachedEnd = 1
			print "Calibrating... I = {} V".format(self.U)

			# n times current with self.U in one direction (plus)
			self.K2401.write(":SOUR:VOLT:LEV {:.2e}".format(self.U))
			for i in range(n):
				if self.stopFlag:
					break

				self.K2401.write(":SOUR:VOLT:LEV {:.2e}".format(self.U))

				if not ((abs(self.U) == self.U_min) and (i == 0)):
					time.sleep(wait)

				if self.use_cryo:
					self.cryostat.updateStatus()
					self.T_cryo = self.cryostat.cryoTemp
					self.T_sample = self.cryostat.sampleTemp

				t = time.time() - t0
				# Sourcemeter voltage, current and resistance
				U, I, R = self.sense_UIR()
				# Voltmeter voltage at sample
				self.K2182.write(":READ?")
				U_sample = float(self.K2182.read())

				data = np.array([self.T_sample, self.T_cryo, U, I, R, U_sample, t])
				self.latestDataPoint = data

				data_string = self.delimiter.join(str(x) for x in data)
				with open(path, 'a') as file:
					file.write(data_string + '\n')

				if plot:
					self._temperatureRun_updatePlot(function='IVcurve')
					# Avoid Matplotlib window crashing:
					#plt.pause(0.05)
					# actually makes Matplotlib window crash when running function in Thread

			# n times resistance with self.I in other direction (minus)
			self.U = -self.U
			self.K2401.write(":SOUR:VOLT:LEV {:.2e}".format(self.U))
			for i in range(n):
				if self.stopFlag:
					break

				if not ((abs(self.U) == self.U_min) and (i == 0)):
					time.sleep(wait)

				if self.use_cryo:
					self.cryostat.updateStatus()
					self.T_cryo = self.cryostat.cryoTemp
					self.T_sample = self.cryostat.sampleTemp

				t = time.time() - t0
				# Sourcemeter voltage, current and resistance
				U, I, R = self.sense_UIR()
				# Voltmeter voltage at sample
				self.K2182.write(":READ?")
				U_sample = float(self.K2182.read())

				data = np.array([self.T_sample, self.T_cryo, U, I, R, U_sample, t])
				self.latestDataPoint = data

				data_string = self.delimiter.join(str(x) for x in data)
				with open(path, 'a') as file:
					file.write(data_string + '\n')

				if plot:
					self._temperatureRun_updatePlot(function='IVcurve')
					# Avoid Matplotlib window crashing:
					#plt.pause(0.05)
					# actually makes Matplotlib window crash when running function in Thread
			self.U = -self.U

#			avgplus = Rarrayplus.sum()/n
#			avgminus = Rarrayminus.sum()/n
#			stdplus = Rarrayplus.std()
#			stdminus = Rarrayminus.std()
#			avg = (avgplus + avgminus)/2
#			std = (stdplus + stdminus)/2
#			rel = abs(std/avg)
#			print "Spread = {} %\n".format(rel*100)
#			if rel < rel_max:
#				print "Calibration successful: Current setpoint set to " \
#					  "{} A.\n".format(self.I)
#				break
			self.U = step * self.U

		# turn off output
		self.K2401.write(":OUTP OFF")
		# set to supply current
		self.K2401.write(":SOUR:FUNC CURR")
		self.calibrateActive = 0
		self.b0.color = 'lightgray'
		self.b0.hovercolor = 'lightskyblue'
		self.b0.label.set_text('Calibrate I')

	def URUIR(self, n=1, deltaMode=1):
		"""
		Returns all measurement functions as arrays of length n.
		:param n:
		:param deltaMode:
		:return: U_sample, R_sample, U_source, I_source, R_source
		"""
		# Check if OUTPut is already on. Device beeps when OUTPut is
		# turned ON, this is to avoid turning it ON and OFF repeatedly.
		self.K2401.write(":OUTP?")
		outputOnInitially = int(self.K2401.read())

		U_sample = np.zeros(n)
		U_sample_neg = np.zeros(n)
		R_sample = np.zeros(n)
		R_sample_neg = np.zeros(n)
		U_source = np.zeros(n)
		U_source_neg = np.zeros(n)
		I_source = np.zeros(n)
		I_source_neg = np.zeros(n)
		R_source = np.zeros(n)
		R_source_neg = np.zeros(n)

		if not outputOnInitially:
			self.K2401.write(":SOUR:CURR:LEV {:.2e}".format(self.I))
			self.K2401.write(":OUTP ON")

		for i in range(n):
			self.K2182.write(":READ?")
			U_sample[i] = float(self.K2182.read())
			U_source[i], I_source[i], R_source[i] = self.sense_UIR()
			if deltaMode == 1:
				# switch current and calculate average
				self.K2401.write(":SOUR:CURR:LEV {:.2e}".format(-self.I))
				self.K2182.write(":READ?")
				U_sample_neg[i] = float(self.K2182.read())
				U_source_neg[i], I_source_neg[i], R_source_neg[i] = self.sense_UIR()
				self.K2401.write(":SOUR:CURR:LEV {:.2e}".format(self.I))

		if not outputOnInitially:
			self.K2401.write(":OUTP OFF")

		R_sample = U_sample/I_source
		if deltaMode == 1:
			R_sample_neg = U_sample_neg/I_source_neg
			R_sample = 0.5*(R_sample + R_sample_neg)
			R_source = 0.5*(R_source + R_source_neg)
		if n == 1:
			U_sample = U_sample[0]
			R_sample = R_sample[0]
			U_source = U_source[0]
			I_source = I_source[0]
			R_source = R_source[0]
		return U_sample, R_sample, U_source, I_source, R_source

	# GUI components for the different measurement runs  - - - - - - - -

	def stop(self):
		""" Raises stop flag, disables stop button.
		"""
		self.stopFlag = 1
		message = 'Stopped'
		try:
			self._temperatureAutoRun_updateStatus(message=message, showcolor=0)
		except AttributeError:
			pass
		self.stopButtonActive = self._temperatureAutoRun_updateStopButton('OFF')
		plt.draw()

	def _temperatureRun_updatePlot(self, function='measure'):
		""" Updates plot with latest data. Changes axes depending on
		function, either R over T (function = measure) or R over t
		(function = calibrate, continuous.)
		"""
		if function == 'measure':
			if self.dataShowing == 'measurementData':
				xdata = self.latestDataPoint[0]
				ydata = self.latestDataPoint[4]
				# Add single data point:
				self.ax.plot(xdata, ydata, c='tab:blue', marker='o')
				self.fig.canvas.draw()
			else:
				self.ax.clear()
				self.ax.set_title('Current measurement run:')
				self.ax.set_ylabel('Resistance [Ohms]')
				self.ax.set_xlabel('Temperature [K]')

				path = os.path.join(self.cwd, 'temp.out')
				with open(path, 'r') as file:
					for line in file.read().splitlines()[2:]:
						data = [float(x) for x in line.split(',')]
						xdata = data[0]
						ydata = data[4]
						# Add single data point:
						self.ax.plot(xdata, ydata, c='tab:blue', marker='o')
				self.fig.canvas.draw()

				self.dataShowing = 'measurementData'
				self.dataToSave = 'measurementData'

		elif function == 'calibrate':
			if self.dataShowing == 'callibrationData':
				xdata = self.latestDataPoint[5]
				ydata = self.latestDataPoint[4]
				# Add single data point:
				self.ax.plot(xdata, ydata, c='tab:red', marker='o')
				self.fig.canvas.draw()
			else:
				self.ax.clear()
				self.ax.set_title('Calibration:')
				self.ax.set_ylabel('Resistance [Ohms]')
				self.ax.set_xlabel('Time [s]')

				path = os.path.join(self.cwd, 'cali.out')
				with open(path, 'r') as file:
					for line in file.read().splitlines()[2:]:
						data = [float(x) for x in line.split(',')]
						xdata = data[5]
						ydata = data[4]
						# Add single data point:
						self.ax.plot(xdata, ydata, c='tab:red', marker='o')
				self.fig.canvas.draw()

				self.dataShowing = 'calibrationData'
				self.dataToSave = 'calibrationData'

		elif function == 'continuous':
			if self.dataShowing == 'continuousData':
				xdata = self.latestDataPoint[9]
				ydata = self.latestDataPoint[4]
				# Add single data point:
				self.ax.plot(xdata, ydata, c='tab:green', marker='o')
				self.fig.canvas.draw()
			else:
				self.ax.clear()
				self.ax.set_title('Continuous measurement:')
				self.ax.set_ylabel('Resistance [Ohms]')
				self.ax.set_xlabel('Time [s]')

				path = os.path.join(self.cwd, 'conti.out')
				with open(path, 'r') as file:
					for line in file.read().splitlines()[2:]:
						data = [float(x) for x in line.split(',')]
						xdata = data[9]
						ydata = data[4]
						# Add single data point:
						self.ax.plot(xdata, ydata, c='tab:green', marker='o')
				self.fig.canvas.draw()

				self.dataShowing = 'continuousData'
				self.dataToSave = 'continuousData'

		elif function == 'IVcurve':
			if self.dataShowing == 'IVcurveData':
				xdata = self.latestDataPoint[2]
				ydata = self.latestDataPoint[3]
				# Add single data point:
				self.ax.plot(xdata, ydata, c='tab:red', marker='o')
				self.fig.canvas.draw()
			else:
				self.ax.clear()
				self.ax.set_title('I-V curve:')
				self.ax.set_xlabel('Voltage [V]')
				self.ax.set_ylabel('Current [A]')

				path = os.path.join(self.cwd, 'IVcurve.out')
				with open(path, 'r') as file:
					for line in file.read().splitlines()[2:]:
						data = [float(x) for x in line.split(',')]
						xdata = data[2]
						ydata = data[3]
						# Add single data point:
						self.ax.plot(xdata, ydata, c='tab:red', marker='o')
				self.fig.canvas.draw()

				self.dataShowing = 'IVcurveData'
				self.dataToSave = 'IVcurveData'

	def _temperatureRun_takeMeas(self, event):
		""" Initiates n measurements, updates data file and plot.
		"""
		# check if T is float:
		if isinstance(self.T_sample, float):
			# Number of measurements over which to average:
			n = 15
			U, R, U_source, I_source, R_source = self.URUIR(n=n, deltaMode=1)
			# Resistance standard deviation:
			DR = R.std()
			try:
				U = sum(U) / n
				R = sum(R) / n
				U_source = sum(U_sample) / n
				I_source = sum(I_source) / n
				R_source = sum(R_source) / n
			except TypeError:
				pass
			print "Resistance at {} K = {} Ohms. Spread = {} %.".format(self.T_sample, R, abs(DR/R))

			# When adding columns to the output data table, please
			# adjust the data variable below as well as the
			# self.DataHead array in the temperature(Auto)Run function.
			data = np.array([self.T_sample, self.T_cryo, self.I, U, R, DR, U_source, I_source, R_source, time.time()])
			self.latestDataPoint = data

			path = os.path.join(self.cwd, 'temp.out')
			with open(path, 'a') as file:
				data_string = self.delimiter.join(str(x) for x in data)
				file.write(data_string+'\n')

			self._temperatureRun_updatePlot(function='measure')
		else:
			print "Please enter valid Temperature!"

	def _temperatureRun_continuousMeas(self, plot=0, n=1):
		""" Continuously measures resistance until interrupted.
		:param plot: Boolean to determine whether to self.updatePlot
		:param n : Number of measurements over which to average
		"""
		self.ContiHead = np.array([["T_sample", "T_cryo", "I_setpoint", "U_sample", "R_sample", "DR", "U_source", "I_source", "R_source", "t"],
							 ["K", "K", "A", "V", "Ohms", "Ohms", "V", "A", "Ohms", "s"]])

		self.K2401.write(":OUTP ON")
		t0 = time.time()

		path = os.path.join(self.cwd, 'conti.out')
		with open(path, 'w') as file:
			for line in self.ContiHead:
				string = self.delimiter.join(str(x) for x in line)
				file.write(string + '\n')
		while (self.stopFlag == 0) and (self.stopContinuousFlag == 0):
			#self.K2401.write(":OUTP ON")
			t = time.time() - t0

			U, R, U_source, I_source, R_source = self.URUIR(n=n, deltaMode=1)
			# Resistance standard deviation:
			DR = 0
			if n > 1:
				DR = R.std()
				U = sum(U) / n
				R = sum(R) / n
				U_source = sum(U_sample) / n
				I_source = sum(I_source) / n
				R_source = sum(R_source) / n

			if self.use_cryo:
				self.cryostat.updateStatus()
				self.T_cryo = self.cryostat.cryoTemp
				self.T_sample = self.cryostat.sampleTemp

			data = np.array([self.T_sample,self.T_cryo, self.I, U, R, DR, U_source, I_source, R_source, t])
			self.latestDataPoint = data

			data_string = self.delimiter.join(str(x) for x in data)

			with open(path, 'a') as file:
				file.write(data_string + '\n')

			if plot:
				self._temperatureRun_updatePlot(function='continuous')
			#self.K2401.write(":OUTP OFF")
			#time.sleep(60)
			#if t >= 5*60*60:
			#	break

		self.K2401.write(":OUTP OFF")

	def _temperatureRun_startContinuous(self, event):
		""" Callback function for the 'Continuous' button.
		Starts new thread for continuous measurement function.
		"""
		if self.continuousActive:
			try:
				self._temperatureAutoRun_updateStatus()
			except AttributeError:
				pass
			plt.draw()
			self.stopContinuousFlag = 1
			self.continuousActive = 0
			self.b7.color = 'lightgray'
			self.b7.hovercolor = 'lightskyblue'
			self.b7.label.set_text('Continuous')
		elif not self.continuousActive:
			try:
				self._temperatureAutoRun_updateStatus('continuous measurement...', 1)
			except AttributeError:
				pass
			plt.draw()
			self.stopFlag = 0
			self.stopContinuousFlag = 0
			target = self._temperatureRun_continuousMeas
			# plotting enabled: args = (1,)
			title = 'Enable plotting?'
			message = 'Would you like to enable live plotting? (Can cause instability with long measurements)'
			plotbool = tkMessageBox.askyesno(title, message)
			args = (plotbool,)
			self.measurement = Thread(target=target, args=args)
			self.measurement.start()
			self.continuousActive = 1
			self.b7.color = 'lightskyblue'
			self.b7.hovercolor = 'lightgray'
			self.b7.label.set_text('Stop')
			self.dataShowing = ''
			self.dataToSave = 'continuousData'

	def _temperatureRun_updateT(self, event):
		""" Textbox callback function to update Temperature. Checks only
		if input is float like.
		"""
		try:
			self.T_sample = float(event)
		except:
			pass

	def _temperatureRun_updateLimit(self, event):
		""" Textbox callback function to update limit of measurement
		spread. Checks only if input is float-like.
		"""
		try:
			self.limit = float(event)
		except:
			pass

	def _temperatureRun_updateI_userInput(self, event):
		""" Textbox callback function to update current, checks only if
		input is float-like.
		"""
		try:
			self.I_userInput = float(event)
		except:
			print "Please enter valid current!"

	def _temperatureRun_updateI(self, event):
		""" Enables manual change of the K2401 current setpoint by user,
		if requested value is within limits.
		"""
		if abs(self.I_userInput) > self.I_max:
			print "Maximum allowed current I_max = {} A.".format(self.I_max)
			self.I = np.sign(self.I_userInput)*self.I_max
			self.t2.set_val(self.I)
		elif abs(self.I_userInput) < self.I_min:
			print "Minimum possible current I_min = {} A.".format(self.I_min)
			self.I = np.sign(self.I_userInput)*self.I_min
			self.t2.set_val(self.I)
		else:
			print "Current updated to {} A.".format(self.I_userInput)
			self.I = self.I_userInput
		self.K2401.write(":SOUR:CURR:RANG {:.2e}".format(self.I))
		self.K2401.write(":SOUR:CURR:LEV {:.2e}".format(self.I))
		self.t2.set_val(self.I)

	def _temperatureRun_calibrate(self, event):
		""" Calls calibration function self.calibrate() upon button
		press, updates textbox.
		"""
		if self.calibrateActive:
			try:
				self._temperatureAutoRun_updateStatus()
			except AttributeError:
				pass
			plt.draw()
			self.stopFlag = 1
			self.calibrateActive = 0
			self.b0.color = 'lightgray'
			self.b0.hovercolor = 'lightskyblue'
			self.b0.label.set_text('Calibrate I')
		elif not self.calibrateActive:
			# DIALOG NOCH VERBESSERN #######################################
			if tkMessageBox.askyesno(title='I-V', message='I(V) instead of R(I)?'):
				try:
					self._temperatureAutoRun_updateStatus('calibrating...', 1)
				except AttributeError:
					pass
				plt.draw()
				self.stopFlag = 0
				target = self.IVcurve
				args = (10, 2, 0.0, 1)
				self.calibration = Thread(target=target, args=args)
				self.calibration.start()
				self.calibrateActive = 1
				self.b0.color = 'lightskyblue'
				self.b0.hovercolor = 'lightgray'
				self.b0.label.set_text('Stop')
				self.dataShowing = ''
				self.dataToSave = 'IVcurveData'
			else:
				try:
					self._temperatureAutoRun_updateStatus('calibrating...', 1)
				except AttributeError:
					pass
				plt.draw()
				self.stopFlag = 0
				target = self.calibrate
				args = (10, 2, 0.0, 1)
				self.calibration = Thread(target=target, args=args)
				self.calibration.start()
				self.calibrateActive = 1
				self.b0.color = 'lightskyblue'
				self.b0.hovercolor = 'lightgray'
				self.b0.label.set_text('Stop')
				self.dataShowing = ''
				self.dataToSave = 'calibrationData'
				self.t2.set_val(self.I)

	def _temperatureRun_saveFile(self, event):
		""" Opens dialog to save DataTable to .csv file.
		"""
		dstn_path = 0
		if self.dataToSave:
			ftypes = [('CSV files', 'csv'), ('All files', '*')]
			dstn_path = tkFileDialog.asksaveasfilename(filetypes=ftypes,
													  defaultextension='.csv')

		if dstn_path:
			if self.dataToSave == 'measurementData':
				src_path = os.path.join(self.cwd, 'temp.out')
			elif self.dataToSave == 'calibrationData':
				src_path = os.path.join(self.cwd, 'cali.out')
			elif self.dataToSave == 'continuousData':
				src_path = os.path.join(self.cwd, 'conti.out')
			elif self.dataToSave == 'IVcurveData':
				src_path = os.path.join(self.cwd, 'IVcurve.out')

			# Copy appropriate temporary file to new location
			with open(src_path, 'r') as src, open(dstn_path, 'w') as dstn:
				dstn.write(src.read())
			print "File saved to {}.".format(dstn_path)

	def _temperatureRun_exit(self, event):
		""" Ask user confirmation to exit measurement, then remove
		temporary data and/or close CryoConnector, as applicable.
		"""
		if tkMessageBox.askokcancel('Exit Measurement', 'Are you sure you want to exit the current Measurement?'):
			self.stopFlag = 1
			try:
				os.remove(os.path.join(self.cwd, 'temp.out'))
			except WindowsError:
				pass

			try:
				self.cryostat.CryoConnector.kill()
			except AttributeError:
				pass

			plt.close()

	def _temperatureRun_clearLast(self, event):
		""" Ask user confirmation, then clear last entry in current
		file and update plot.
		"""
		if tkMessageBox.askokcancel('Clear last', 'Clear last data point?'):
			if self.dataShowing == 'measurementData':
				path = os.path.join(self.cwd, 'temp.out')
				function = 'measure'
			elif self.dataShowing == 'continuousData':
				path = os.path.join(self.cwd, 'conti.out')
				function = 'continuous'
			elif self.dataShowing == 'calibrationData':
				path = os.path.join(self.cwd, 'cali.out')
				function = 'calibrate'
			else:
				raise Exception
			with open(path, "r+") as file:		# encoding = "utf-8" ?

				# Move the pointer to the end of the file:
				file.seek(0, os.SEEK_END)

				# This code means the following code skips the last two
				# character in the file - i.e. in the case the last line
				# is null we delete the last line & the penultimate one.
				pos = file.tell() - 2

				# Read each character in the file one at a time from the
				# penultimate character going backwards, searching for a
				# newline character. If we find a new line, exit search.
				while pos > 0 and file.read(1) != "\n":
					pos -= 1
					file.seek(pos, os.SEEK_SET)

				# So long as we're not at the start of the file, delete
				# all the characters ahead of this position.
				if pos > 0:
					file.seek(pos+1, os.SEEK_SET)
					file.truncate()

				# Re-add newline charakter at the end of the file.
				#file.write('\n')
			self.dataShowing = ''
			self._temperatureRun_updatePlot(function)

	def _temperatureRun_clearAll(self, event):
		""" Ask user confirmation, then clear current data file, update
		plot.
		"""
		if tkMessageBox.askokcancel('Clear all', 'Clear all data points?'):
			if self.dataShowing == 'measurementData':
				path = os.path.join(self.cwd, 'temp.out')
				function = 'measure'
				head = self.DataHead
			elif self.dataShowing == 'calibrationData':
				path = os.path.join(self.cwd, 'cali.out')
				function = 'calibrate'
				head = self.CaliHead
			elif self.dataShowing == 'continuousData':
				path = os.path.join(self.cwd, 'conti.out')
				function = 'continuous'
				head = self.ContiHead
			else:
				raise Exception
			with open(path, 'w') as file:
				for line in head:
					string = self.delimiter.join(str(x) for x in line)
					file.write(string + '\n')
			self.dataShowing = ''
			self._temperatureRun_updatePlot(function=function)

	def _temperatureRun_stopButton(self, event):
		""" Callback function for the stop button, which raises the stop
		flag via the stop() function. """
		if self.stopButtonActive:
			self.stop()
			self.stopButtonActive = 0
			self._temperatureAutoRun_updateStopButton()

	def _addButton(self):
		""" Callback function for the button to add a stage to the measurement program.
		"""
		try:
			values = [float(e.get()) for e in self.entries]
			if self.use_apex:
				values.append(self.variable.get())
			row_id = self.tree.focus()
			if row_id:
				self.tree.insert('', self.tree.index(row_id)+1, values=values)
			else:
				self.tree.insert('', 'end', values=values)
			return 0
		except ValueError:
			print 'Please enter valid values!'
			return 1

	def _okayButton(self):
		""" Callback function for the okay button.
		"""
		error = self._addButton()
		if not error:
			self.addStageWindow.destroy()

	def _closeButton(self):
		""" Callback function for the close button.
		"""
		self.addStageWindow.destroy()

	def _addStage(self):
		""" Callback function for add stage button, opens submenu.
		"""
		self.addStageWindow = tk.Tk()
		self.addStageWindow.title('Add stage')

		self.variable = tk.StringVar()
		self.variable.set(self.XRDlist[0])

		self.label0 = tk.Label(self.addStageWindow, text='Please enter:')
		self.label0.grid(row=1, column=0)

		self.labels = []
		self.entries = []
		i = 0
		for text in self.columns:
			if not text == 'XRD sweep':
				self.labels.append(tk.Label(self.addStageWindow, text=text))
				self.entries.append(tk.Entry(self.addStageWindow))
				self.labels[i].grid(row=0, column=i+1)
				self.entries[i].grid(row=1, column=i+1)
				i = i+1
			else:
				self.labelx = tk.Label(self.addStageWindow, text=text)
				self.labelx.grid(row=0, column=i+1)
				self.menu = tk.OptionMenu(self.addStageWindow, self.variable, *self.XRDlist)	# need * to pass as list
				self.menu.grid(row=1, column=i+1)

		ccb1 = tk.Button(self.addStageWindow, text='Add', command=self._addButton)
		ccb1.grid(row=2, column=i, sticky='E')

		ccb2 = tk.Button(self.addStageWindow, text='Close', command=self._closeButton)
		ccb2.grid(row=2, column=i+1, sticky='EW')

	def _deleteStage(self):
		""" Callback function for the delete stage button.
		"""
		selection = self.tree.selection()
		if selection:
			for row_id in selection:
				self.tree.delete(row_id)
		else:
			print 'Nothing selected.'

	def _moveUp(self):
		""" Callback function to move element up in tree.
		"""
		row_id = self.tree.focus()
		if row_id:
			self.tree.move(row_id, self.tree.parent(row_id), self.tree.index(row_id)-1)

	def _moveDown(self):
		""" Callback function to move element down in tree.
		"""
		row_id = self.tree.focus()
		if row_id:
			self.tree.move(row_id, self.tree.parent(row_id), self.tree.index(row_id)+1)

	def _configureXrayScans(self):
		""" Not implemented.
		"""
		pass

	def _closeConfigWindow(self):
		""" Callback function for OK button. Saves list of stages and
		closes the window.
		"""
		self.stageList = []
		for child in self.tree.get_children():
			string_values = self.tree.item(child)["values"]
			float_values = [float(value) for value in string_values]
			self.stageList.append(float_values)
		path = os.path.join(self.cwd, 'stageList.out')
		np.savetxt(path, self.stageList, fmt='%s') #, fmt='%s'
		self.configWindow.destroy()

	def _temperatureAutoRun_configureRun(self, event):
		""" Callback function for configure run button. Tries to load
		previously saved configuration, opens submenu.
		"""
		# Try loading previously configured run.
		if os.path.isfile(os.path.join(self.cwd, 'stageList.out')):
			try:
				stageArray = np.genfromtxt(os.path.join(self.cwd, 'stageList.out'), dtype=float)
				self.stageList = stageArray.tolist()
			except UserWarning:
				pass

		# Configure Tkinter window.
		self.configWindow = tk.Tk()
		self.configWindow.title('Configure measurement run')

		# Configure treeview and initiate iid (item id) as 0.
		if self.use_apex:
			self.columns = ('Target temperature [K]',
							'Cooling rate [K/min]',
							'Step width [K]',
							'Wait before measure [min]',
							'XRD sweep')
		else:
			self.columns = ('Target temperature [K]',
							'Cooling rate [K/min]',
							'Step width [K]',
							'Wait before measure [min]')
		self.tree = ttk.Treeview(self.configWindow, columns=self.columns)
		self.tree['show'] = 'headings'

		for row in self.stageList:
			self.tree.insert('', 'end', values=row)

		self.tree.heading('#0', text='#')
		self.tree.column('#0', width=60, minwidth=60)
		for text in self.columns:
			self.tree.heading(text, text=text)
			self.tree.column(text, width=150, minwidth=150)

		self.tree.grid(row=0, column=0, rowspan=3, columnspan=3)

		cb0 = tk.Button(self.configWindow, text='Add stage', command=self._addStage)
		cb0.grid(row=4, column=0, sticky='EW')

		cb1 = tk.Button(self.configWindow, text='Delete Stage', command=self._deleteStage)
		cb1.grid(row=5, column=0, sticky='EW')

		cb2 = tk.Button(self.configWindow, text='Move up', command=self._moveUp)
		cb2.grid(row=4, column=1, sticky='EW')

		cb3 = tk.Button(self.configWindow, text='Move down', command=self._moveDown)
		cb3.grid(row=5, column=1, sticky='EW')

		if self.use_apex:
			cb4 = tk.Button(self.configWindow, text='Configure X-Ray scans', command=self._configureXrayScans)
			cb4.grid(row=4, column=2, sticky='EW')

		cb5 = tk.Button(self.configWindow, text='OK', command=self._closeConfigWindow)
		cb5.grid(row=5, column=2, sticky='EW')

		self.configWindow.mainloop()

	def _temperatureAutoRun_takeMeas(self):
		""" Successively performs stages of the user-configured
		measurement run. """

		self.dataToSave = 'measurementData'

		# Initiate empty arrays for temperature steps and associated
		# ramp rates and step_widths of all stages:
		program_steps = np.array([])
		program_ramp_rates = np.array([])
		program_step_widths = np.array([])
		program_wait_minutes = np.array([])

		# Initiate time for one resistance measurement in seconds:
		R_probe_time = 10

		# starting_temperature for first stage is current temperature:
		self.cryostat.updateStatus()
		starting_temperature = self.cryostat.sampleTemp

		for stage_parameters in self.stageList:
			final_target_temperature = stage_parameters[0]
			stage_ramp_rate = stage_parameters[1]
			step_width_input = stage_parameters[2]
			wait_minutes = stage_parameters[3]
			wait_seconds = 60 * wait_minutes

			step_width_abs = abs(step_width_input)
			step_width = np.sign(final_target_temperature -
								 starting_temperature) * step_width_abs

			# Create list of intermediate temperature setpoints (steps)
			# inverted, so that start is half-open, rather than stop:
			steps_inverted = np.arange(start=final_target_temperature,
									   stop=starting_temperature,
									   step=(-1)*step_width)

			# Flip list of steps:
			steps = np.flip(steps_inverted)

			# Create arrays of ramp rates and step widths for each step:
			# (step_widths is only used for estimate of total duration)
			ramp_rates = stage_ramp_rate * np.ones(len(steps))
			step_widths = step_width_abs * np.ones(len(steps))
			wait_minutess = wait_minutes * np.ones(len(steps))

			# Append steps, ramp rates and step_widths to program:
			program_steps = np.append(program_steps, steps)
			program_ramp_rates = np.append(program_ramp_rates, ramp_rates)
			program_step_widths = np.append(program_step_widths, step_widths)
			program_wait_minutes = np.append(program_wait_minutes, wait_minutess)

			# starting_temperature for next stage is final setpoint
			# of this stage:
			starting_temperature = final_target_temperature

		# Avoid division by zero in t_to_completion calculation:
		program_ramp_rates_nonzero = program_ramp_rates
		for i in range(len(program_ramp_rates_nonzero)):
			if program_ramp_rates_nonzero[i] == 0:
				program_ramp_rates_nonzero[i] = 1000

		t_start = time.time()
		for i in range(len(program_steps)):
			if self.stopFlag:
				break
			t_elapsed = time.time() - t_start

			# Calculating estimate of remaining time in program:
			ramping_duration = sum(abs(program_step_widths[i:]) / abs(program_ramp_rates_nonzero[i:]) * 60)
			waiting_duration = sum(abs(program_wait_minutes[i:])) * 60
			measuring_duration = R_probe_time * len(program_steps[i:])
			t_to_completion = sum([ramping_duration,
									   waiting_duration,
									   measuring_duration])
			t_of_arrival = time.time() + t_to_completion
			days_elapsed = int(t_elapsed/(60*60*24))
			days_to_completion = int(t_to_completion/(60*60*24))

			# Convert times to formatted strings:
			te = time.strftime('%H:%M:%S', time.gmtime(t_elapsed))
			etc = time.strftime('%H:%M:%S', time.gmtime(t_to_completion))
			eta = time.strftime('%b %d %Y %H:%M:%S', time.gmtime(t_of_arrival)) # time zone wrong

			# Print to console:
			if bool(days_elapsed):
				print 'Elapsed: {} days {} hours'.format(days_elapsed, te)
			else:
				print 'Elapsed: {} hours'.format(te)
			if bool(days_to_completion):
				print 'Estimated time to completion: {} days {} hours\n'.format(days_to_completion, etc)
			else:
				print 'Estimated time to completion: {} hours\n'.format(etc)
			#print 'Started: {}\nEstimated time of completion: {}\n'.format(t_start, eta)

			# Send ramp command to temperature controller:
			self.cryostat.ramp(program_ramp_rates[i], program_steps[i])
			time.sleep(1)
			self.cryostat.updateStatus()

			# Wait for completion of setpoint ramping:
			while self.cryostat.phaseStatus == 'Ramp':
				if self.stopFlag:
					break
				message = ', '.join([self.cryostat.deviceStatus,
									self.cryostat.phaseStatus,
									self.cryostat.alarmStatus])
				if self.cryostat.alarmLevel == 0:
					showcolor = 1
				else:
					showcolor = self.cryostat.alarmLevel

				# Update the status message bar:
				self._temperatureAutoRun_updateStatus(message, showcolor)
				plt.draw()

				if self.cryostat.alarmLevel >= 2:
					self.stopFlag = 1
				if self.stopFlag:
					break
				else:
					time.sleep(1)
					self.cryostat.updateStatus()

			# Wait for temperature to settle before probing resistance:
			t_wait_start = time.time()
			t_waiting = 0
			self.cryostat.updateStatus()
			while t_waiting < 60*program_wait_minutes[i]:
				if self.stopFlag:
					break
				wait_remaining = 60*program_wait_minutes[i] - t_waiting
				wr = time.strftime('%H:%M:%S', time.gmtime(wait_remaining))
				message = ', '.join(['Waiting... -{}'.format(wr),
									self.cryostat.alarmStatus])
				if self.cryostat.alarmLevel == 0:
					showcolor = 1
				else:
					showcolor = self.cryostat.alarmLevel

				# Update the status message bar:
				self._temperatureAutoRun_updateStatus(message, showcolor)
				plt.draw()

				if self.cryostat.alarmLevel >= 2:
					self.stopFlag = 1
				if self.stopFlag:
					break
				else:
					time.sleep(1)
					self.cryostat.updateStatus()
					t_waiting = time.time() - t_wait_start

			# Measure resistance:
			if not self.stopFlag:
				message = 'Measuring resistance...'
				showcolor = 1
				self._temperatureAutoRun_updateStatus(message, showcolor)
				plt.draw()

				self.T_cryo = self.cryostat.cryoTemp
				self.T_sample = self.cryostat.sampleTemp

				t_probe_start = time.time()

				# Take measurement of resistance, write to file:
				self._temperatureRun_takeMeas(event=None)

				# Update time it takes to take one measurement for
				# estimate of t_to_completion (moving)
				new = time.time() - t_probe_start
				R_probe_time = np.mean([new, R_probe_time])

		self.cryostat.updateStatus()
		if self.stopFlag:
			message = ', '.join(['Stopped',
								 self.cryostat.alarmStatus])
			self._temperatureAutoRun_updateStatus(message=message, showcolor=self.cryostat.alarmLevel)
			self.stopButtonActive = self._temperatureAutoRun_updateStopButton('OFF')
			plt.draw()
			if bool(self.cryostat.alarmLevel):
				self.cryostat.stop()
		else:
			message = ', '.join(['Measurement complete',
								 self.cryostat.alarmStatus])
			self._temperatureAutoRun_updateStatus(message=message, showcolor=self.cryostat.alarmLevel)
			self.stopButtonActive = self._temperatureAutoRun_updateStopButton('OFF')
			plt.draw()

	def _temperatureAutoRun_updateStatus(self, message='ready...', showcolor=0):
		""" Updates the status message bar with a message and color
		change. For the showcolor parameter:
		0 is white,
		1 is green,
		2 is yellow,
		3 is orange,
		4 is red,
		and everything else means no change.
		"""
		if showcolor == 0:
			# white
			self.b9.color = 'white'
			self.b9.hovercolor = 'white'
		elif showcolor == 1:
			# green
			self.b9.color = '#C8F7C8'
			self.b9.hovercolor = '#C8F7C8'
		elif showcolor == 2:
			# yellow
			self.b9.color = '#F7F7C8'
			self.b9.hovercolor = '#F7F7C8'
		elif showcolor == 3:
			# orange
			self.b9.color = '#F7D7B7'
			self.b9.hovercolor = '#F7D7B7'
		elif showcolor == 4:
			# red
			self.b9.color = '#F7B7B7'
			self.b9.hovercolor = '#F7B7B7'

		self.b9.label.set_text(message)
		plt.draw()

	def _temperatureAutoRun_updateStopButton(self, setTo='OFF'):
		""" Activates/deactivates the STOP button functionality,
		returns 1/0 for the self.stopButtonActive status variable.
		"""
		if setTo == 'ON':
			self.b8.color = '#E93F3F'
			self.b8.hovercolor = 'lightcoral'
			return 1
		if setTo == 'OFF':
			self.b8.color = '0.95'
			self.b8.hovercolor = '0.95'
			return 0

	def _temperatureAutoRun_start(self, event):
		""" Callback function for the START button. starts the
		user-configured measurement run in a new thread.
		"""
		self._temperatureAutoRun_updateStatus('starting...', 1)
		self.stopButtonActive = self._temperatureAutoRun_updateStopButton('ON')
		plt.draw()
		self.stopFlag = 0
		self.measurement = Thread(target=self._temperatureAutoRun_takeMeas)
		self.measurement.start()

	def temperatureRun(self, n=20):
		""" This function initiates a manual resistance over temperature
		measurement run. The user can enter the temperature which
		the cryostat has been set to externally, then add a
		datapoint/measurement to the run.
		"""

		# When adding columns to the output data table, please adjust
		# the dataHead below as well as the data variable in the
		# _temperatureRun_takeMeas callback function.
		self.DataHead = np.array([["T_sample", "T_cryo", "I_setpoint", "U_sample", "R_sample", "DR", "U_source", "I_source", "R_source", "t"],
							 ["K", "K", "A", "V", "Ohms", "Ohms", "V", "A", "Ohms", "s"]])

		self.fig.set_figheight(6.4)
		self.fig.set_figwidth(6.4)
		self.fig.canvas.set_window_title('Manual R over T measurement')
		plt.subplots_adjust(top=0.95, bottom=0.425)
		self.ax.set_title('Current measurement run:')
		self.ax.set_ylabel('Resistance [Ohms]')
		self.ax.set_xlabel('Temperature [K]')
		self.ax.set_ylim(0, 1000)
		self.ax.set_xlim(0, 300)

		self.I_userInput = self.I

		axb0 = plt.axes([0.4, 0.25, 0.15, 0.075])
		self.b0 = Button(axb0, 'Calibrate I', hovercolor='lightskyblue')
		self.b0.on_clicked(self._temperatureRun_calibrate)

		axt0 = plt.axes([0.3, 0.25, 0.075, 0.075])
		t0 = TextBox(axt0, 'R-spread in % < ', initial=str(self.limit))
		t0.on_submit(self._temperatureRun_updateLimit)

		axb1 = plt.axes([0.4, 0.05, 0.15, 0.075])
		b1 = Button(axb1, 'Measure R', hovercolor='lightskyblue')
		b1.on_clicked(self._temperatureRun_takeMeas)

		axt1 = plt.axes([0.3, 0.05, 0.075, 0.075])
		t1 = TextBox(axt1, 'T in K = ', initial=str(self.T_sample))
		t1.on_submit(self._temperatureRun_updateT)

		axb2 = plt.axes([0.575, 0.25, 0.15, 0.075])
		b2 = Button(axb2, 'Clear last')
		b2.on_clicked(self._temperatureRun_clearLast)

		axb3 = plt.axes([0.575, 0.15, 0.15, 0.075])
		b3 = Button(axb3, 'Clear all')
		b3.on_clicked(self._temperatureRun_clearAll)

		axb4 = plt.axes([0.75, 0.25, 0.15, 0.075])
		b4 = Button(axb4, 'Save to file')
		b4.on_clicked(self._temperatureRun_saveFile)

		axb5 = plt.axes([0.75, 0.15, 0.15, 0.075])
		b5 = Button(axb5, 'Exit', hovercolor='lightcoral')
		b5.on_clicked(self._temperatureRun_exit)

		axt2 = plt.axes([0.3, 0.15, 0.075, 0.075])
		self.t2 = TextBox(axt2, 'I in A = ', initial=str(self.I_userInput))
		self.t2.on_submit(self._temperatureRun_updateI_userInput)

		axb6 = plt.axes([0.4, 0.15, 0.15, 0.075])
		b6 = Button(axb6, 'Update I')
		b6.on_clicked(self._temperatureRun_updateI)

		self.axb7 = plt.axes([0.575, 0.05, 0.15, 0.075])
		self.b7 = Button(self.axb7, 'Continuous', hovercolor='lightskyblue')
		self.b7.on_clicked(self._temperatureRun_startContinuous)

		# STOP button:
		#axb8 = plt.axes([0.75, 0.05, 0.15, 0.075])
		#self.b8 = Button(axb8, 'STOP', color='0.95')
		#self.b8.on_clicked(self._temperatureRun_stopButton)
		#self.stopButtonActive = 0

		# Check for unfinished run data, keep or overwrite temp.out:
		path = os.path.join(self.cwd, 'temp.out')
		if os.path.isfile(path):
			if tkMessageBox.askyesno('Unfinished measurement run found',
									 'Do you want to continue with the previous measurement?'):
				self._temperatureRun_updatePlot(function='measure')
			else:
				with open(path, 'w') as file:
					for line in self.DataHead:
						string = self.delimiter.join(str(x) for x in line)
						file.write(string + '\n')
		else:
			with open(path, 'w') as file:
				for line in self.DataHead:
					string = self.delimiter.join(str(x) for x in line)
					file.write(string + '\n')

		plt.show()

		# Delete files if no measurement has been performed:
		if not self.latestDataPoint.any():
			try:
				os.remove(os.path.join(self.cwd, 'temp.out'))
			except WindowsError:
				pass

	def temperatureAutoRun(self, n=20):
		""" This function scans the resistance of a connected sample
		fully automatically by incorporating remote control of supported
		cryostats via the Cryostat.py module.
		"""
		self.DataHead = np.array([["T_sample", "T_cryo", "I_setpoint", "U_sample", "R_sample", "DR", "U_source", "I_source", "R_source", "t"],
							 ["K", "K", "A", "V", "Ohms", "Ohms", "V", "A", "Ohms", "s"]])

		self.fig.set_figheight(7.4)
		self.fig.set_figwidth(6.4)

		self.fig.canvas.set_window_title('Automatic R over T measurement')

		plt.subplots_adjust(top=0.95, bottom=0.525)
		self.ax.set_title('Current measurement run:')
		self.ax.set_ylabel('Resistance [Ohms]')
		self.ax.set_xlabel('Temperature [K]')
		self.ax.set_ylim(0, 1000)
		self.ax.set_xlim(0, 300)

		self.I_userInput = self.I

		# Calibrate I button:
		axb0 = plt.axes([0.4, 0.35, 0.15, 0.075])
		self.b0 = Button(axb0, 'Calibrate I', hovercolor='lightskyblue')
		self.b0.on_clicked(self._temperatureRun_calibrate)

		# Maximum Resistance spread text input box:
		axt0 = plt.axes([0.3, 0.35, 0.075, 0.075])
		t0 = TextBox(axt0, 'R-spread in % < ', initial=str(self.limit))
		t0.on_submit(self._temperatureRun_updateLimit)

		# Configure run button:
		axb1 = plt.axes([0.125, 0.15, 0.25, 0.075])
		b1 = Button(axb1, 'Configure run')
		b1.on_clicked(self._temperatureAutoRun_configureRun)

		axb2 = plt.axes([0.575, 0.35, 0.15, 0.075])
		b2 = Button(axb2, 'Clear last')
		b2.on_clicked(self._temperatureRun_clearLast)

		axb3 = plt.axes([0.575, 0.25, 0.15, 0.075])
		b3 = Button(axb3, 'Clear all')
		b3.on_clicked(self._temperatureRun_clearAll)

		axb4 = plt.axes([0.75, 0.35, 0.15, 0.075])
		b4 = Button(axb4, 'Save to file')
		b4.on_clicked(self._temperatureRun_saveFile)

		axb5 = plt.axes([0.75, 0.25, 0.15, 0.075])
		b5 = Button(axb5, 'Exit', hovercolor='lightcoral')
		b5.on_clicked(self._temperatureRun_exit)

		axt2 = plt.axes([0.3, 0.25, 0.075, 0.075])
		self.t2 = TextBox(axt2, 'I in A = ', initial=str(self.I_userInput))
		self.t2.on_submit(self._temperatureRun_updateI_userInput)

		axb6 = plt.axes([0.4, 0.25, 0.15, 0.075])
		b6 = Button(axb6, 'Update I')
		b6.on_clicked(self._temperatureRun_updateI)

		axb7 = plt.axes([0.4, 0.15, 0.15, 0.075])
		b7 = Button(axb7, 'Start run', hovercolor='lightskyblue')
		b7.on_clicked(self._temperatureAutoRun_start)

		self.axb7 = plt.axes([0.575, 0.15, 0.15, 0.075])
		self.b7 = Button(self.axb7, 'Continuous', hovercolor='lightskyblue')
		self.b7.on_clicked(self._temperatureRun_startContinuous)

		# STOP button:
		axb8 = plt.axes([0.75, 0.05, 0.15, 0.075])
		self.b8 = Button(axb8, 'STOP', color='0.95')
		self.b8.on_clicked(self._temperatureRun_stopButton)
		self.stopButtonActive = 0

		# Status message box:
		axb9 = plt.axes([0.125, 0.05, 0.6, 0.075])
		self.b9 = Button(axb9, 'ready...', color='white', hovercolor='white')
		self.b9.label.set_style('italic')

		# Check for unfinished run data, keep or overwrite temp.out:
		path = os.path.join(self.cwd, 'temp.out')
		if os.path.isfile(path):
			if tkMessageBox.askyesno('Unfinished measurement run found',
									 'Do you want to continue with the previous measurement?'):
				self._temperatureRun_updatePlot(function='measure')
			else:
				with open(path, 'w') as file:
					for line in self.DataHead:
						string = self.delimiter.join(str(x) for x in line)
						file.write(string + '\n')
		else:
			with open(path, 'w') as file:
				for line in self.DataHead:
					string = self.delimiter.join(str(x) for x in line)
					file.write(string + '\n')

		plt.show()

		# Delete files if no measurement has been performed:
		if not self.latestDataPoint.any():
			try:
				os.remove(os.path.join(self.cwd, 'temp.out'))
			except WindowsError:
				pass


def main():

	Bi4I4 = ResistanceMeasurement(testMode=1)


if __name__ == "__main__":
	main()