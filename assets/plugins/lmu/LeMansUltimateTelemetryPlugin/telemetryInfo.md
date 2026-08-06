# Telemetry

## Fields Exposed for Telemetry (TelemInfoV01)

### **General Information**

* Type: "TelemInfoV01"
* mID
* mDeltaTime
* mElapsedTime
* mLapNumber
* mLapStartET
* mVehicleName
* mTrackName

### **Position and Derivatives**

* mPos:
    * x
    * y
    * z
* mLocalVel:
    * x
    * y
    * z
* mLocalAccel:
    * x
    * y
    * z

### **Orientation and Derivatives**

* mOri: (Array of 3D vectors)
    * [x, y, z] (first vector)
    * [x, y, z] (second vector)
    * [x, y, z] (third vector)
* mLocalRot:
    * x
    * y
    * z
* mLocalRotAccel:
    * x
    * y
    * z

### **Vehicle Status**

* mGear
* mEngineRPM
* mEngineWaterTemp
* mEngineOilTemp
* mClutchRPM

### **Driver Input - Unfiltered**

* mUnfilteredThrottle
* mUnfilteredBrake
* mUnfilteredSteering
* mUnfilteredClutch

### **Driver Input - Filtered**

* mFilteredThrottle
* mFilteredBrake
* mFilteredSteering
* mFilteredClutch

### **Miscellaneous**

* mSteeringShaftTorque
* mFront3rdDeflection
* mRear3rdDeflection

### **Aerodynamics**

* mFrontWingHeight
* mFrontRideHeight
* mRearRideHeight
* mDrag
* mFrontDownforce
* mRearDownforce

### **State/Damage Information**

* mFuel
* mEngineMaxRPM
* mScheduledStops
* mOverheating
* mDetached
* mHeadlights
* mDentSeverity: (Array of unsigned chars)
* mLastImpactET
* mLastImpactMagnitude
* mLastImpactPos:
    * x
    * y
    * z

### **Expanded Fields**

* mEngineTorque
* mCurrentSector
* mSpeedLimiter
* mMaxGears
* mFrontTireCompoundIndex
* mRearTireCompoundIndex
* mFuelCapacity
* mFrontFlapActivated
* mRearFlapActivated
* mRearFlapLegalStatus
* mIgnitionStarter
* mFrontTireCompoundName
* mRearTireCompoundName
* mSpeedLimiterAvailable
* mAntiStallActivated
* mUnused: (Array of 2 integers)
* mVisualSteeringWheelRange
* mRearBrakeBias
* mTurboBoostPressure
* mPhysicsToGraphicsOffset: (Array of 3 floats)
* mPhysicalSteeringWheelRange
* mBatteryChargeFraction

### **Electric Boost Motor**

* mElectricBoostMotorTorque
* mElectricBoostMotorRPM
* mElectricBoostMotorTemperature
* mElectricBoostWaterTemperature
* mElectricBoostMotorState

### **Future Use**

* mExpansion: (Array of unsigned chars)

### **Wheel Information (mWheel - Array of 4 Wheel objects)**

Each mWheel object (serialized via SerializeWheel which calls WheelToJson) contains:

* suspensionDeflection
* rideHeight
* suspForce
* brakeTemp
* brakePressure
* rotation
* lateralPatchVel
* longitudinalPatchVel
* lateralGroundVel
* longitudinalGroundVel
* camber
* lateralForce
* longitudinalForce
* tireLoad
* gripFract
* pressure
* temperature: (Array of 3 floats)
* wear
* terrainName
* surfaceType
* flat
* detached
* staticUndeflectedRadius
* verticalTireDeflection
* wheelYLocation
* toe
* tireCarcassTemperature
* tireInnerLayerTemperature: (Array of 3 floats)

## Fields Exposed for Scoring (ScoringInfoV01)

### **General Information**

* Type: "ScoringInfoV01"
* mTrackName
* mSession
* mCurrentET
* mEndET
* mMaxLaps
* mLapDist
* mNumVehicles
* mGamePhase
* mYellowFlagState
* mSectorFlag: (Array of 3 integers)
* mStartLight
* mNumRedLights
* mInRealtime
* mPlayerName
* mPlrFileName

### **Weather**

* mDarkCloud
* mRaining
* mAmbientTemp
* mTrackTemp
* mWind:
    * x
    * y
    * z
* mMinPathWetness
* mMaxPathWetness
* mAvgPathWetness

### **Multiplayer**

* mGameMode
* mIsPasswordProtected
* mServerPort
* mServerPublicIP
* mMaxPlayers
* mServerName
* mStartET
* mResultsStream (if not null)

### **Vehicle Scoring Information (mVehicles - Array of VehicleScoringInfoV01 objects)**

Each mVehicles object (serialized via SerializeVehicleScoringInfo) contains:

* mID
* mDriverName
* mVehicleName
* mVehicleClass
* mPlace
* mControl
* mIsPlayer

#### **Lap & Sector**

* mTotalLaps
* mSector
* mFinishStatus
* mLapDist
* mPathLateral
* mTrackEdge

#### **Timing**

* mBestSector1
* mBestSector2
* mBestLapTime
* mLastSector1
* mLastSector2
* mLastLapTime
* mCurSector1
* mCurSector2
* mLapStartET
* mTimeIntoLap
* mEstimatedLapTime

#### **Relative Gaps**

* mTimeBehindNext
* mLapsBehindNext
* mTimeBehindLeader
* mLapsBehindLeader

#### **Pit Info**

* mNumPitstops
* mNumPenalties
* mInPits
* mPitGroup
* mPitState
* mPitLapDist

#### **Positional Data**

* mPos:
    * x
    * y
    * z
* mLocalVel:
    * x
    * y
    * z
* mLocalAccel:
    * x
    * y
    * z

#### **Orientation**

* mOri: (Array of 3D vectors)
    * [x, y, z] (first vector)
    * [x, y, z] (second vector)
    * [x, y, z] (third vector)
* mLocalRot:
    * x
    * y
    * z
* mLocalRotAccel:
    * x
    * y
    * z

#### **Flags & State**

* mHeadlights
* mFlag
* mUnderYellow
* mCountLapFlag
* mInGarageStall