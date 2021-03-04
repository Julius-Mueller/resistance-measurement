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

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.widgets import Button
from matplotlib.widgets import TextBox

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
		self.I_Range = self.I_Range_init	# Sourcemeter current range
		self.I_min = 50e-12					# Min sourcemeter current
		self.I_max = 1e-6					# Max safe current
		self.I = self.I_min					# Current setpoint in A
		self.T = 300.0						# Temperature, initially RT
		self.limit = 5.0					# Limit for R-spread in %
		self.stageList = []					# List of stages in meas.run
		self.XRDlist = ('None',)			# List of XRD sweep names

		self.stopFlag = 0					# Measurement run stop flag

		self.fig, self.ax = plt.subplots()	# Initiate GUI root window
		self.ax.useblit=1

		self.rm = visa.ResourceManager()

		# WIP functionality
		self.use_keit = 0					# Use KEITHLEY hardware y/n
		self.use_cryo = 0					# Use cryostat hardware y/n
		self.use_apex = 0					# Use Bruker APEX PC y/n
		self.start()

	# start function to initialise the measurement environment - - - - -

	def _addCryostatButton(self):
		""" Callback function for the Cryostat button in self.start. Initialises cryostat. """
		self.cryostat = Cryostat(CCWorkingFolder=self.CCcwd, testMode=self.testMode)
		if not (self.cryostat.index == -1):
			self.text1.set(self.cryostat.deviceName)
			self.use_cryo = 1

	def connectK2401(self, port):
		""" Attempts to initialise the Keithely K2401 Sourcemeter at the provided port. """
		self.K2401 = self.rm.open_resource("GPIB0::{:.0f}::INSTR".format(port))
		self.K2401.read_termination = '\n'
		self.K2401.write_termination = '\n'

		self.K2401.write("*RST")										# reset GPIB
		self.K2401.write(":ROUT:TERM FRON")								# select terminals
		self.K2401.write(":SYST:RSEN OFF")								# no measuring with 2401
		self.K2401.write(":SOUR:FUNC CURR")								# set to supply current
		self.K2401.write(":SOUR:CURR:MODE FIX")							# fixed current mode
		self.K2401.write(":SOUR:CURR:RANG {:.2e}".format(self.I_Range))	# source range
		self.K2401.write(":SOUR:CURR:LEV {:.2e}".format(self.I))		# source amplitude

	def connectK2182(self, port):
		""" Attempts to initialise the Keithely K2182 Voltmeter at the provided port. """
		self.K2182 = self.rm.open_resource("GPIB0::{:.0f}::INSTR".format(port))
		self.K2182.read_termination = '\n'
		self.K2182.write_termination = '\n'

		self.K2182.write("*RST")										# reset GPIB
		self.K2182.write(":SENS:FUNC 'VOLT'")							# select voltage
		self.K2182.write(":SENS:CHAN 1")								# select channel 1
		self.K2182.write(":SENS:VOLT:CHAN1:RANG:AUTO ON")				# auto range on

	def _testK2401(self):
		""" Tests whether the K2401 is connected to the selected port. """
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
		""" Tests whether the K2182 is connected to the selected port. """
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
		self.use_keit = (self.use_K2401 and self.use_K2182)
		if self.use_keit:
			self.text0.set('K2401 & K2182')
		self.keithleyWindow.destroy()

	def _addKeithleysButton(self):
		""" Callback function for the Keithley Sourcemeter/Voltmeter button in self.start. Initialises K2401, K2821. """
		ports = range(31)												# Keithley device addresses range from 0-30

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
		""" Callback function for the OK-button in self.start. Decides which measurement run to initialise based on the
		selected hardware and closes the startWindow."""
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
		""" Asks the user which hardware to connect to and starts the measurement GUI. """
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
		""" Measures voltage directly or via delta-mode. Returns n values as array."""
		self.K2401.write(":OUTP?")										# Check if OUTPut is already on. Device beeps
		outputOnInitially = int(self.K2401.read())						# when OUTPut is turned ON, so avoid turning it
																		# ON and OFF repeatedly.

		U = np.zeros(n)
		U_neg = np.ones(n)
		self.K2401.write(":SOUR:CURR:RANG {:.2e}".format(self.I_Range))
		self.K2401.write(":SOUR:CURR:LEV {:.2e}".format(self.I))

		if not outputOnInitially:
			self.K2401.write(":OUTP ON")

		for i in range(n):
			self.K2182.write(":READ?")
			U[i] = float(self.K2182.read())
			if deltaMode == 1:											# switch current and calculate average
				self.K2401.write(":SOUR:CURR:LEV -{:.2e}".format(self.I))
				self.K2182.write(":READ?")
				U_neg[i] = float(self.K2182.read())
				self.K2401.write(":SOUR:CURR:LEV {:.2e}".format(self.I))

		if not outputOnInitially:
			self.K2401.write(":OUTP OFF")

		#print U
		#print U_neg
		if deltaMode == 1:
			U = 0.5*(U - U_neg)
		return U

	def resistance(self, n=1, deltaMode=1):
		""" Measures voltage() and calculates resistance. Returns n values as array."""
		U = self.voltage(n=n, deltaMode=deltaMode)
		R = U / self.I
		return R

	def calibrate(self, n=10, step=10):
		""" Ramps up the current until spread of measured resistances (std) is smaller than the self.limit in %.
			n is the number of measurements per current setting, step is the multiplicative increase of the current
			setpoint until desired precision is reached.
		"""
		rel_max = self.limit*0.01
		self.I = self.I_min
		slow = 0

		self.K2401.write(":OUTP ON")

		while True:
			if (self.I > self.I_max) and (slow == 0):
				slow = 1
				if step > 5.0:
					self.I = self.I/step
					step = step/5.0
					self.I = step * self.I
			if (self.I > self.I_max) and (slow == 1):
				self.I = self.I_min
				self.I_Range = self.I_Range_init
				print "Calibration failed: Reached current threshold before measurement spread within limits!"
				print "Current setpoint returned to {} A.\n".format(self.I)
				break
			print "Calibrating... I = {} A".format(self.I)
			R = self.resistance(n=n)
			avg = sum(R) / len(R)
			print avg, "Ohms"	########## remove later? ###############################
			std = R.std()
			rel = abs(std/avg)
			print "Spread = {} %\n".format(rel*100)
			if rel < rel_max:
				print "Calibration successful: Current setpoint set to {} A.\n".format(self.I)
				break
			self.I = step * self.I
			self.I_Range = self.I

		self.K2401.write(":OUTP OFF")

	# GUI components for the different measurement runs  - - - - - - - -

	def stop(self):
		self.stopButtonActive = self._temperatureAutoRun_updateStopButton('OFF')
		self._temperatureAutoRun_updateStatus(message='stopped', showcolor=0)
		plt.draw()
		self.stopFlag = 0

	def _temperatureRun_updatePlot(self):
		""" Updates plot with current DataTable entries. """
		self.ax.clear()
		self.ax.set_title('Current measurement run:')
		self.ax.set_ylabel('Resistance [Ohms]')
		self.ax.set_xlabel('Temperature [K]')

		xdata = self.DataTable[2:, 0].astype(np.float)
		ydata = self.DataTable[2:, 3].astype(np.float)
		self.l = self.ax.scatter(xdata, ydata)
		self.fig.canvas.draw()

	def _temperatureRun_takeMeas(self, event):
		""" Initiates n measurements, adds single average data point to DataTable and updates temporary data file. """
		if isinstance(self.T, float):									# check if T is float
			n = 5														# Number of measurements over which to average
			U = self.voltage(n=n)
			R = U / self.I
			DR = R.std()												# resistance statistical error
			U = sum(U) / len(U)
			R = sum(R) / len(R)
			print "Resistance at {} K = {} Ohms. Spread = {} %.".format(self.T, R, abs(DR/R))

			# When adding columns to the output data table, please adjust the data variable below as well as the
			# self.DataHead array in the main temperature(Auto)Run function.
			data = np.array([self.T, self.I, U, R, DR, time.time()])

			self.DataTable = np.vstack((self.DataTable, data))			# vstack changes all dtype to dtype of first arg
																		# ... thus the .astype(np.float) in updatePlot.
			self._temperatureRun_updatePlot()
			np.savetxt(os.path.join(self.cwd, 'temp.out'), self.DataTable, fmt='%s')
		else:
			print "Please enter valid Temperature!"

	def _temperatureRun_updateT(self, event):
		""" Textbox callback function to update Temperature. Checks only if input is float like. """
		try:
			self.T = float(event)
		except:
			pass

	def _temperatureRun_updateLimit(self, event):
		""" Textbox callback function to update limit of measurement spread. Checks only if input is float-like."""
		try:
			self.limit = float(event)
		except:
			pass

	def _temperatureRun_updateI_userInput(self, event):
		""" Textbox callback function to update current, checks only if input is float-like. """
		try:
			self.I_userInput = float(event)
		except:
			print "Please enter valid current!"

	def _temperatureRun_updateI(self, event):
		""" Enables manual change of the K2401 current setpoint by user, if requested value is within limits. """
		if abs(self.I_userInput) > self.I_max:
			print "Maximum allowed current I_max = {} A.".format(self.I_max)
			self.I = self.I_max
			self.t2.set_val(self.I)
		elif abs(self.I_userInput) < self.I_min:
			print "Minimum possible current I_min = {} A.".format(self.I_min)
			self.I = self.I_min
			self.t2.set_val(self.I)
		else:
			print "Current updated to {} A.".format(self.I_userInput)
			self.I = self.I_userInput
		self.K2401.write(":SOUR:CURR:RANG {:.2e}".format(self.I))
		self.K2401.write(":SOUR:CURR:LEV {:.2e}".format(self.I))
		self.t2.set_val(self.I)

	def _temperatureRun_calibrate(self, event):
		""" Calls calibration function self.calibrate() upon button press, updates textbox. """
		self.calibrate(n=10)
		self.t2.set_val(self.I)

	def _temperatureRun_saveFile(self, event):
		""" Opens dialog to save DataTable to .csv file. """
		ftypes = [('CSV files', 'csv'), ('All files', '*')]
		try:
			filename = tkFileDialog.asksaveasfilename(filetypes=ftypes, defaultextension='.csv')
			np.savetxt(filename, self.DataTable, delimiter=";", fmt="%s")
			print "File saved."
		except:
			pass

	def _temperatureRun_exit(self, event):
		""" Ask user confirmation to exit measurement, then remove temporary data and/or close CryoConnector, as
			applicable.
		"""
		if tkMessageBox.askokcancel('Exit Measurement', 'Are you sure you want to exit the current Measurement?'):
			try:
				os.remove(os.path.join(self.cwd, 'temp.out'))
			except:
				pass

			try:
				self.cryostat.CryoConnector.kill()
			except AttributeError:
				pass

			plt.close()

	def _temperatureRun_clearLast(self, event):
		""" Ask user confirmation, then clear last entry in current DataTable. """
		if len(self.DataTable[:, 0]) < 3:
			print "No data points to clear."
		elif tkMessageBox.askokcancel('Clear last', 'Clear last data point?'):
			self.DataTable = self.DataTable[:-1, :]
			self._temperatureRun_updatePlot()

	def _temperatureRun_clearAll(self, event):
		""" Ask user confirmation, then clear current DataTable. """
		if len(self.DataTable[:, 0]) < 3:
			print "No data points to clear."
		elif tkMessageBox.askokcancel('Clear all', 'Clear all data points?'):
			self.DataTable = self.DataHead
			self._temperatureRun_updatePlot()

	def _addButton(self):
		""" Callback function for the button to add a stage to the measurement program. """
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
		error = self._addButton()
		if not error:
			self.addStageWindow.destroy()

	def _closeButton(self):
		self.addStageWindow.destroy()

	def _addStage(self):
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
		row_id = self.tree.focus()
		if row_id:
			self.tree.delete(row_id)
		else:
			print 'Nothing selected.'

	def _moveUp(self):
		row_id = self.tree.focus()
		if row_id:
			self.tree.move(row_id, self.tree.parent(row_id), self.tree.index(row_id)-1)

	def _moveDown(self):
		row_id = self.tree.focus()
		if row_id:
			self.tree.move(row_id, self.tree.parent(row_id), self.tree.index(row_id)+1)

	def _configureXrayScans(self):
		pass

	def _closeConfigWindow(self):
		self.stageList = []
		for child in self.tree.get_children():
			self.stageList.append(self.tree.item(child)["values"])
		self.configWindow.destroy()

	def _temperatureAutoRun_configureRun(self, event):

		# Configure Tkinter window.
		self.configWindow = tk.Tk()
		self.configWindow.title('Configure measurement run')

		# Configure treeview and initiate iid (item id) as 0.
		if self.use_apex:
			self.columns = ('Target temperature [K]', 'Cooling rate [K/h]', 'Step width [K]', 'XRD sweep')
		else:
			self.columns = ('Target temperature [K]', 'Cooling rate [K/h]', 'Step width [K]')
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

	def _temperatureAutoRun_stopButton(self, event):
		""" Callback function for the stop button, which raises the stop
			flag. """
		if self.stopButtonActive:
			self.stopFlag = 1

	def _temperatureAutoRun_takeMeas(self):
		""" Successively performs stages of the user-configured
			measurement run. """
		for i in range(20):
			if self.stopFlag:
				self.stop()
				break
			time.sleep(1)
			self._temperatureAutoRun_updateStatus(message=str(i), showcolor=1)
			plt.draw()


	def _temperatureAutoRun_updateStatus(self, message='ready...', showcolor=0):
		""" Updates the status message bar with a message and color change. For the showcolor parameter:
			0 is white
			1 is green,
			4 is red,
			everything else means no change.
		"""
		if showcolor == 0:
			# white
			self.b9.color = 'white'
			self.b9.hovercolor = 'white'
		elif showcolor == 1:
			# green
			self.b9.color = '#C8F7C8'
			self.b9.hovercolor = '#C8F7C8'
		elif showcolor == 4:
			# red
			self.b9.color = '#F7B7B7'
			self.b9.hovercolor = '#F7B7B7'

		self.b9.label.set_text(message)

	def _temperatureAutoRun_updateStopButton(self, setTo='OFF'):
		if setTo == 'ON':
			self.b8.color = '#E93F3F'
			self.b8.hovercolor = 'lightcoral'
			return 1
		if setTo == 'OFF':
			self.b8.color = '0.95'
			self.b8.hovercolor = '0.95'
			return 0

	def _temperatureAutoRun_start(self, event):
		self._temperatureAutoRun_updateStatus('starting...', 1)
		self.stopButtonActive = self._temperatureAutoRun_updateStopButton('ON')
		plt.draw()
		self.measurement = Thread(target=self._temperatureAutoRun_takeMeas)
		self.measurement.start()

	def temperatureRun(self, n=20):
		""" This function initiates a manual resistance over temperature measurement run. The user can enter the
			temperature which the cryostat has been set to externally, then add a datapoint/measurement to the run.
		"""

		# When adding columns to the output data table, please adjust the dataHead below as well as the data variable
		# in the _temperatureRun_takeMeas callback function.
		self.DataHead = np.array([["T", "I", "U", "R", "DR", "t"],
							 ["K", "A", "V", "Ohms", "Ohms", "s"]])

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
		b0 = Button(axb0, 'Calibrate I', hovercolor='lightskyblue')
		b0.on_clicked(self._temperatureRun_calibrate)

		axt0 = plt.axes([0.3, 0.25, 0.075, 0.075])
		t0 = TextBox(axt0, 'R-spread in % < ', initial=str(self.limit))
		t0.on_submit(self._temperatureRun_updateLimit)

		axb1 = plt.axes([0.4, 0.05, 0.15, 0.075])
		b1 = Button(axb1, 'Measure R', hovercolor='lightskyblue')
		b1.on_clicked(self._temperatureRun_takeMeas)

		axt1 = plt.axes([0.3, 0.05, 0.075, 0.075])
		t1 = TextBox(axt1, 'T in K = ', initial=str(self.T))
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

		# Check for unfinished run data, initiate DataTable
		if os.path.isfile(os.path.join(self.cwd, 'temp.out')):
			self.DataTable = np.genfromtxt(os.path.join(self.cwd, 'temp.out'))
			if len(self.DataTable[0]) == len(self.DataHead[0]) and tkMessageBox.askyesno(
					'Unfinished measurement run found',
					'Do you want to continue with the previous measurement?'
			):
				self._temperatureRun_updatePlot()
			else:
				self.DataTable = self.DataHead
		else:
			self.DataTable = self.DataHead

		plt.show()

	def temperatureAutoRun(self, n = 20):
		""" WORK IN PROGRESS
			This function scans the resistance of a connected sample fully automatically by incorporating remote control
			of supported cryostats via the Cryostat.py module.
		"""

		self.DataHead = np.array([["T", "I", "U", "R", "t"],
				  			 ["K", "A", "V", "Ohms", "s"]])

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
		b0 = Button(axb0, 'Calibrate I', hovercolor='lightskyblue')
		b0.on_clicked(self._temperatureRun_calibrate)

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

		# STOP button:
		axb8 = plt.axes([0.75, 0.05, 0.15, 0.075])
		self.b8 = Button(axb8, 'STOP', color='0.95')
		self.b8.on_clicked(self._temperatureAutoRun_stopButton)
		self.stopButtonActive = 0

		# Status message box:
		axb9 = plt.axes([0.125, 0.05, 0.6, 0.075])
		self.b9 = Button(axb9, 'ready...', color='white', hovercolor='white')
		self.b9.label.set_style('italic')

		# Check for unfinished run data, initiate DataTable
		if os.path.isfile(os.path.join(self.cwd, 'temp.out')):
			self.DataTable = np.genfromtxt(os.path.join(self.cwd, 'temp.out'))
			if len(self.DataTable[0]) == len(self.DataHead[0]) and tkMessageBox.askyesno(
															'Unfinished measurement run found',
															'Do you want to continue with the previous measurement?'
															):
				self._temperatureRun_updatePlot()
			else:
				self.DataTable = self.DataHead
		else:
			self.DataTable = self.DataHead

		plt.show()



def main():

	Bi4I4 = ResistanceMeasurement(testMode=1)

#	Bi4I4.I = 5e-8

#	Bi4I4.temperatureAutoRun()
#	Bi4I4.temperatureRun()


#	R = Bi4I4.resistance(n=1)
#	print R


if __name__ == "__main__":
	main()